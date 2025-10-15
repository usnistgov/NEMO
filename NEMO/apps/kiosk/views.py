from datetime import datetime, time, timedelta
from http import HTTPStatus
from typing import Dict, List

from django.conf import settings
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_time
from django.utils.html import format_html
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from NEMO.decorators import synchronized
from NEMO.exceptions import ProjectChargeException, RequiredUnansweredQuestionsException
from NEMO.forms import CommentForm, ConsumableWithdrawForm, TaskForm, nice_errors
from NEMO.models import (
    BadgeReader,
    Consumable,
    ConsumableWithdraw,
    Project,
    Reservation,
    TaskCategory,
    TaskStatus,
    Tool,
    ToolUsageQuestionType,
    ToolWaitList,
    UsageEvent,
    User,
)
from NEMO.policy import policy_class as policy
from NEMO.utilities import localize, quiet_int, remove_duplicates
from NEMO.views.area_access import log_out_user
from NEMO.views.calendar import cancel_the_reservation, set_reservation_configuration, shorten_reservation
from NEMO.views.consumables import (
    consumable_permissions,
    make_withdrawal,
    make_withdrawal_success_message,
    self_checkout,
)
from NEMO.views.customization import ApplicationCustomization, ToolCustomization, UserCustomization
from NEMO.views.get_projects import get_projects
from NEMO.views.tasks import save_task
from NEMO.views.tool_control import (
    email_managers_required_questions_disable_tool,
    interlock_bypass_allowed,
    interlock_error,
    save_comment,
    tool_configuration,
)


@login_required
@permission_required("NEMO.kiosk")
@require_POST
def enable_tool(request):
    return do_enable_tool(request, request.POST["tool_id"])


@synchronized("tool_id")
def do_enable_tool(request, tool_id):
    tool = Tool.objects.get(id=tool_id)
    customer = User.objects.get(id=request.POST["customer_id"])
    project = Project.objects.get(id=request.POST["project_id"])
    bypass_interlock = request.POST.get("bypass", "False") == "True"

    response = policy.check_to_enable_tool(
        tool, operator=customer, user=customer, project=project, staff_charge=False, remote_work=False
    )
    if response.status_code != HTTPStatus.OK:
        dictionary = {
            "message": "You are not authorized to enable this tool. {}".format(response.content.decode()),
            "delay": 10,
        }
        return render(request, "kiosk/acknowledgement.html", dictionary)

    # All policy checks passed so enable the tool for the user.
    if tool.interlock and not tool.interlock.unlock():
        if bypass_interlock and interlock_bypass_allowed(customer, tool):
            pass
        else:
            return interlock_error("Enable", customer, tool)

    # Create a new usage event to track how long the user uses the tool.
    new_usage_event = UsageEvent()
    new_usage_event.operator = customer
    new_usage_event.user = customer
    new_usage_event.project = project
    new_usage_event.tool = tool

    # Collect pre-usage questions
    dynamic_forms = tool.get_usage_questions(ToolUsageQuestionType.PRE, project)

    try:
        new_usage_event.pre_run_data = dynamic_forms.extract(request)
    except RequiredUnansweredQuestionsException as e:
        dictionary = {"message": str(e), "delay": 10}
        return render(request, "kiosk/acknowledgement.html", dictionary)

    # Validate usage event
    try:
        new_usage_event.full_clean()
    except ValidationError as e:
        return render(request, "kiosk/acknowledgement.html", {"message": str(e)})

    new_usage_event.save()

    # Remove wait list entry if it exists
    wait_list_entry = ToolWaitList.objects.filter(tool=tool, expired=False, deleted=False, user=customer)
    if wait_list_entry.count() > 0:
        wait_list_entry.update(deleted=True, date_exited=timezone.now())

    try:
        dynamic_forms.process_run_data(new_usage_event, new_usage_event.pre_run_data, request)
    except Exception as e:
        dictionary = {"message": str(e), "delay": 10}
        return render(request, "kiosk/acknowledgement.html", dictionary)

    dictionary = {"message": "You can now use the {}".format(tool), "badge_number": customer.badge_number}
    return render(request, "kiosk/acknowledgement.html", dictionary)


@login_required
@permission_required("NEMO.kiosk")
@require_POST
def disable_tool(request):
    return do_disable_tool(request, request.POST["tool_id"])


@synchronized("tool_id")
def do_disable_tool(request, tool_id):
    tool = Tool.objects.get(id=tool_id)
    customer: User = User.objects.get(id=request.POST["customer_id"])
    downtime = timedelta(minutes=quiet_int(request.POST.get("downtime")))
    bypass_interlock = request.POST.get("bypass", "False") == "True"
    response = policy.check_to_disable_tool(tool, customer, downtime)
    if response.status_code != HTTPStatus.OK:
        dictionary = {"message": response.content, "delay": 10}
        return render(request, "kiosk/acknowledgement.html", dictionary)

    # All policy checks passed so try to disable the tool for the user.
    if tool.interlock and not tool.interlock.lock():
        if bypass_interlock and interlock_bypass_allowed(customer, tool):
            pass
        else:
            return interlock_error("Disable", customer, tool)

    # Shorten the user's tool reservation since we are now done using the tool
    current_usage_event = tool.get_current_usage_event()
    staff_shortening = request.POST.get("shorten", False)
    shorten_reservation(
        user=current_usage_event.user, item=tool, new_end=timezone.now() + downtime, force=staff_shortening
    )

    # End the current usage event for the tool and save it.
    current_usage_event.end = timezone.now() + downtime

    # Collect post-usage questions
    dynamic_forms = tool.get_usage_questions(ToolUsageQuestionType.POST)

    try:
        current_usage_event.run_data = dynamic_forms.extract(request)
    except RequiredUnansweredQuestionsException as e:
        if customer != current_usage_event.operator and current_usage_event.user != customer:
            # if someone else is forcing somebody off the tool and there are required questions, send an email and proceed
            current_usage_event.run_data = e.run_data
            email_managers_required_questions_disable_tool(current_usage_event, customer, e.questions)
        else:
            dictionary = {"message": str(e), "delay": 10}
            return render(request, "kiosk/acknowledgement.html", dictionary)

    try:
        dynamic_forms.process_run_data(current_usage_event, current_usage_event.run_data, request)
    except Exception as e:
        dictionary = {"message": str(e), "delay": 10}
        return render(request, "kiosk/acknowledgement.html", dictionary)

    current_usage_event.save()
    dictionary = {
        "message": "You are no longer using the {}".format(tool),
        "badge_number": customer.badge_number,
        "delay": 1,
    }
    record = customer.area_access_record()
    if record and tool.ask_to_leave_area_when_done_using:
        dictionary["tool"] = tool
        dictionary["area"] = record.area
        dictionary["delay"] = 10
        dictionary["ask_logout"] = True
    return render(request, "kiosk/acknowledgement.html", dictionary)


@login_required
@permission_required("NEMO.kiosk")
@require_POST
def enter_wait_list(request):
    tool = Tool.objects.get(id=request.POST["tool_id"])
    customer = User.objects.get(id=request.POST["customer_id"])

    if not tool.allow_wait_list():
        dictionary = {
            "message": "{} does not operate in wait list mode. ".format(tool),
            "delay": 10,
        }
        return render(request, "kiosk/acknowledgement.html", dictionary)

    wait_list_other_users = ToolWaitList.objects.filter(tool=tool, expired=False, deleted=False).exclude(user=customer)
    wait_list_user_entry = ToolWaitList.objects.filter(tool=tool, expired=False, deleted=False, user=customer)

    # User must not be in the wait list
    if wait_list_user_entry.count() > 0:
        dictionary = {"message": "You are already in the wait list.", "delay": 10}
        return render(request, "kiosk/acknowledgement.html", dictionary)

    # The tool must be in use or have a wait list
    current_usage_event = tool.get_current_usage_event()
    if not current_usage_event and wait_list_other_users.count() == 0:
        dictionary = {"message": "The tool is free to use.", "delay": 10}
        return render(request, "kiosk/acknowledgement.html", dictionary)

    # The user must be qualified to use the tool itself or the parent tool in case of an alternate tool.
    tool_to_check_qualifications = tool.parent_tool if tool.is_child_tool() else tool
    if tool_to_check_qualifications not in customer.qualifications.all() and not customer.is_staff_on_tool(tool):
        dictionary = {"message": "You are not qualified to use this tool.", "delay": 10}
        return render(request, "kiosk/acknowledgement.html", dictionary)

    entry = ToolWaitList()
    entry.user = customer
    entry.tool = tool
    entry.save()

    return redirect("kiosk_tool_information", tool_id=tool.id, user_id=customer.id, back="back_to_category")


@login_required
@permission_required("NEMO.kiosk")
@require_POST
def exit_wait_list(request):
    tool = Tool.objects.get(id=request.POST["tool_id"])
    customer = User.objects.get(id=request.POST["customer_id"])
    wait_list_entry = ToolWaitList.objects.filter(tool=tool, expired=False, deleted=False, user=customer)
    if wait_list_entry.count() == 0:
        dictionary = {"message": "You are not in the wait list.", "delay": 10}
        return render(request, "kiosk/acknowledgement.html", dictionary)
    do_exit_wait_list(wait_list_entry, timezone.now())
    return redirect("kiosk_tool_information", tool_id=tool.id, user_id=customer.id, back="back_to_category")


def do_exit_wait_list(entry, time):
    entry.update(deleted=True, date_exited=time)


@login_required
@permission_required("NEMO.kiosk")
@require_POST
def reserve_tool(request):
    virtual_inputs = request.GET.get("virtual_inputs") != "false"
    tool = Tool.objects.get(id=request.POST["tool_id"])
    customer = User.objects.get(id=request.POST["customer_id"])
    project = Project.objects.get(id=request.POST["project_id"])
    back = request.POST["back"]

    dictionary = {"back": back, "tool": tool, "project": project, "customer": customer}

    """ Create a reservation for a user. """
    try:
        start_date = parse_date(request.POST["start_date"])
        end_date = parse_date(request.POST["end_date"])
        start = localize(datetime.combine(start_date, parse_time(request.POST["start"])))
        end = localize(datetime.combine(end_date, parse_time(request.POST["end"])))
    except:
        dictionary["message"] = (
            "Please enter a valid start date, start time, end date and end time for the reservation."
        )
        return render(request, "kiosk/error.html", dictionary)
    # Create the new reservation:
    reservation = Reservation()
    reservation.project = project
    reservation.user = customer
    reservation.creator = customer
    reservation.reservation_item = tool
    reservation.start = start
    reservation.end = end
    reservation.short_notice = tool.determine_insufficient_notice(start)
    policy_problems, overridable = policy.check_to_save_reservation(
        cancelled_reservation=None,
        new_reservation=reservation,
        user_creating_reservation=customer,
        explicit_policy_override=False,
    )

    # If there was a problem in saving the reservation then return the error...
    if policy_problems:
        dictionary["message"] = policy_problems[0]
        return render(request, "kiosk/error.html", dictionary)

    # All policy checks have passed.
    if project is None and not customer.is_staff_on_tool(tool):
        dictionary["message"] = "You must specify a project for your reservation"
        return render(request, "kiosk/error.html", dictionary)

    dynamic_forms = tool.get_reservation_questions(reservation.project)
    tool_config = tool.is_configurable()
    needs_extra_config = dynamic_forms or tool_config
    if needs_extra_config and not request.POST.get("configured") == "true":
        dictionary.update(tool.get_configuration_information(user=customer, start=reservation.start))
        dictionary.update(
            {
                "request_start_date": request.POST["start_date"],
                "request_end_date": request.POST["end_date"],
                "request_start": request.POST["start"],
                "request_end": request.POST["end"],
                "reservation": reservation,
                "reservation_questions": dynamic_forms.render(virtual_inputs=virtual_inputs),
            }
        )
        return render(request, "kiosk/tool_reservation_extra.html", dictionary)

    set_reservation_configuration(reservation, request)
    # Reservation can't be short notice if the user is configuring the tool themselves.
    if reservation.self_configuration:
        reservation.short_notice = False

    # Reservation questions if applicable
    try:
        reservation.question_data = dynamic_forms.extract(request)
    except RequiredUnansweredQuestionsException as e:
        dictionary["message"] = str(e)
        return render(request, "kiosk/error.html", dictionary)

    reservation.save_and_notify()
    return render(request, "kiosk/success.html", {"new_reservation": reservation, "customer": customer})


@login_required
@permission_required("NEMO.kiosk")
@require_POST
def cancel_reservation(request, reservation_id):
    """Cancel a reservation for a user."""
    reservation = Reservation.objects.get(id=reservation_id)
    customer = User.objects.get(id=request.POST["customer_id"])

    response = cancel_the_reservation(reservation=reservation, user_cancelling_reservation=customer, reason=None)

    if response.status_code == HTTPStatus.OK:
        return render(request, "kiosk/success.html", {"cancelled_reservation": reservation, "customer": customer})
    else:
        return render(request, "kiosk/error.html", {"message": response.content, "customer": customer})


@login_required
@permission_required("NEMO.kiosk")
@require_POST
def kiosk_tool_configuration(request):
    # Use the badged-in user as the user making the request and call the configuration directly
    request.user = User.objects.get(badge_number=request.GET["badge_number"])
    return tool_configuration(request)


@login_required
@permission_required("NEMO.kiosk")
@require_POST
def tool_reservation(request, tool_id, user_id, back):
    tool = Tool.objects.get(id=tool_id, visible=True)
    customer = User.objects.get(id=user_id)
    project = Project.objects.get(id=request.POST["project_id"])

    dictionary = {
        "tool": tool,
        "date": None,
        "project": project,
        "customer": customer,
        "back": back,
        "tool_reservation_times": list(
            Reservation.objects.filter(
                cancelled=False, missed=False, shortened=False, tool=tool, start__gte=timezone.now()
            )
        ),
    }

    return render(request, "kiosk/tool_reservation.html", dictionary)


@login_required
@permission_required("NEMO.kiosk")
@require_GET
def choices(request):
    try:
        categories = request.GET.getlist("category")
        tool_names = request.GET.getlist("tool")
        customer = User.objects.get(badge_number=request.GET["badge_number"])
        usage_events = (
            UsageEvent.objects.filter(operator=customer.id, end=None)
            .order_by("tool__name")
            .prefetch_related("tool", "project")
        )
        tools_in_use = [u.tool.tool_or_parent_id() for u in usage_events]
        fifteen_minutes_from_now = timezone.now() + timedelta(minutes=15)
        tool_reservations = (
            Reservation.objects.filter(
                tool__isnull=False,
                end__gt=timezone.now(),
                user=customer,
                missed=False,
                cancelled=False,
                shortened=False,
            )
            .exclude(tool_id__in=tools_in_use, start__lte=fifteen_minutes_from_now)
            .exclude(ancestor__shortened=True)
            .order_by("start")
        )
    except:
        dictionary = {
            "message": "Your badge wasn't recognized. If you got a new one recently then we'll need to update your account. Please contact staff to resolve the problem."
        }
        return render(request, "kiosk/acknowledgement.html", dictionary)

    show_access_expiration_banner = False
    expiration_warning = UserCustomization.get_int("user_access_expiration_banner_warning")
    expiration_danger = UserCustomization.get_int("user_access_expiration_banner_danger")
    if customer.access_expiration and (expiration_warning or expiration_danger):
        access_expiration_datetime = datetime.combine(customer.access_expiration, time.min).astimezone()
        if access_expiration_datetime >= timezone.now():
            if expiration_warning and access_expiration_datetime < timezone.now() + timedelta(days=expiration_warning):
                show_access_expiration_banner = "warning"
            if expiration_danger and access_expiration_datetime < timezone.now() + timedelta(days=expiration_danger):
                show_access_expiration_banner = "danger"

    dictionary = {
        "show_access_expiration_banner": show_access_expiration_banner,
        "now": timezone.now(),
        "customer": customer,
        "usage_events": list(usage_events),
        "upcoming_reservations": tool_reservations,
        "show_consumable_self_checkout": ApplicationCustomization.get_bool("kiosk_consumable_checkout")
        and consumable_permissions(customer),
        **get_categories_and_tools_dictionary(customer, categories, tool_names),
    }
    return render(request, "kiosk/choices.html", dictionary)


@login_required
@permission_required("NEMO.kiosk")
@require_GET
def category_choices(request, category, user_id):
    try:
        customer = User.objects.get(id=user_id)
    except:
        dictionary = {
            "message": "Your badge wasn't recognized. If you got a new one recently then we'll need to update your account. Please contact staff to resolve the problem."
        }
        return render(request, "kiosk/acknowledgement.html", dictionary)
    dictionary = {
        "customer": customer,
        **get_categories_and_tools_dictionary(customer, [category]),
    }
    return render(request, "kiosk/category_choices.html", dictionary)


@login_required
@permission_required("NEMO.kiosk")
@require_GET
def tool_information(request, tool_id, user_id, back):
    virtual_inputs = request.GET.get("virtual_inputs") != "false"
    tool = Tool.objects.get(id=tool_id, visible=True)
    customer = User.objects.get(id=user_id)
    wait_list = tool.current_wait_list()
    user_wait_list_entry = wait_list.filter(user=user_id).first()
    user_wait_list_position = (
        (
            ToolWaitList.objects.filter(
                tool=tool, date_entered__lte=user_wait_list_entry.date_entered, expired=False, deleted=False
            )
            .exclude(user=customer)
            .count()
            + 1
        )
        if user_wait_list_entry
        else 0
    )
    tool_credentials = []
    if ToolCustomization.get_bool("tool_control_show_tool_credentials") and (
        customer.is_staff_on_tool(tool) or customer.is_facility_manager
    ):
        if customer.is_facility_manager:
            tool_credentials = tool.toolcredentials_set.all()
        else:
            tool_credentials = tool.toolcredentials_set.filter(
                Q(authorized_staff__isnull=True) | Q(authorized_staff__in=[customer])
            )
    post_usage_questions = tool.get_usage_questions(ToolUsageQuestionType.POST)
    dictionary = {
        "customer": customer,
        "tool": tool,
        "tool_credentials": tool_credentials,
        "rendered_configuration_html": tool.configuration_widget(
            customer, url=reverse("kiosk_tool_configuration") + "?badge_number=" + str(customer.badge_number)
        ),
        "post_usage_questions": (
            post_usage_questions.render(virtual_inputs=virtual_inputs) if post_usage_questions else ""
        ),
        "back": back,
        "tool_control_show_task_details": ToolCustomization.get_bool("tool_control_show_task_details"),
        "wait_list_position": user_wait_list_position,  # 0 if not in wait list
        "wait_list": wait_list,
        "show_wait_list": (
            tool.allow_wait_list()
            and (
                not (
                    tool.get_current_usage_event().operator.id == customer.id
                    or tool.get_current_usage_event().user.id == customer.id
                )
                if tool.in_use()
                else wait_list.count() > 0
            )
        ),
    }

    current_reservation = Reservation.objects.filter(
        start__lt=timezone.now(),
        end__gt=timezone.now(),
        cancelled=False,
        missed=False,
        shortened=False,
        user=customer,
        tool=tool,
    ).last()
    if current_reservation:
        remaining_reservation_duration = int((current_reservation.end - timezone.now()).total_seconds() / 60)
        # We don't need to bother telling the user their reservation will be shortened if there's less than two minutes left.
        # Staff are exempt from reservation shortening.
        if remaining_reservation_duration > 2:
            dictionary["remaining_reservation_duration"] = remaining_reservation_duration

    return render(request, "kiosk/tool_information.html", dictionary)


@login_required
@permission_required("NEMO.kiosk")
@require_GET
def kiosk(request, location=None):
    return render(request, "kiosk/kiosk.html", {"badge_reader": get_badge_reader(request)})


@login_required
@permission_required("NEMO.kiosk")
@require_GET
def logout_user(request, tool_id):
    tool = Tool.objects.get(pk=tool_id)
    if not tool.ask_to_leave_area_when_done_using:
        dictionary = {"message": "You are not allowed to logout of the area from this page"}
        return render(request, "kiosk/acknowledgement.html", dictionary)
    customer = User.objects.get(badge_number=request.GET["badge_number"])
    record = customer.area_access_record()
    if record is None:
        dictionary = {"message": "You are not logged into any areas"}
        return render(request, "kiosk/acknowledgement.html", dictionary)
    log_out_user(customer)
    dictionary = {
        "message": f"You have been successfully logged out of the {record.area}",
        "delay": 1,
    }
    return render(request, "kiosk/acknowledgement.html", dictionary)


def get_badge_reader(request) -> BadgeReader:
    reader_id = request.GET.get("reader_id") or ApplicationCustomization.get_int("default_badge_reader_id")
    try:
        badge_reader = BadgeReader.objects.get(id=reader_id)
    except BadgeReader.DoesNotExist:
        badge_reader = BadgeReader.default()
    return badge_reader


@login_required
@permission_required("NEMO.kiosk")
@require_POST
def tool_report_problem(request, tool_id, user_id, back):
    tool = Tool.objects.get(id=tool_id, visible=True)
    customer = User.objects.get(id=user_id)

    dictionary = {
        "tool": tool,
        "customer": customer,
        "back": back,
        "task_categories": TaskCategory.objects.filter(stage=TaskCategory.Stage.INITIAL_ASSESSMENT),
        "task_statuses": TaskStatus.objects.all(),
    }

    return render(request, "kiosk/tool_report_problem.html", dictionary)


@login_required
@permission_required("NEMO.kiosk")
@require_POST
def report_problem(request):
    tool = Tool.objects.get(id=request.POST["tool"])
    customer = User.objects.get(id=request.POST["customer_id"])
    back = request.POST["back"]

    dictionary = {
        "tool": tool,
        "customer": customer,
        "back": back,
        "task_categories": TaskCategory.objects.filter(stage=TaskCategory.Stage.INITIAL_ASSESSMENT),
        "task_statuses": TaskStatus.objects.all(),
    }

    """ Report a problem for a tool. """
    form = TaskForm(customer, data=request.POST)

    try:
        date = parse_date(request.POST["estimated_resolution_dt"])
        estimated_resolution_time = localize(
            datetime.combine(date, parse_time(request.POST["estimated_resolution_tm"]))
        )
    except:
        estimated_resolution_time = None

    if not form.is_valid():
        errors = nice_errors(form)

        dictionary["message"] = errors.as_ul()
        dictionary["estimated_resolution_dt"] = request.POST.get("estimated_resolution_dt")
        dictionary["estimated_resolution_tm"] = request.POST.get("estimated_resolution_tm")
        dictionary["form"] = form

        return render(request, "kiosk/tool_report_problem.html", dictionary)

    if not settings.ALLOW_CONDITIONAL_URLS and form.cleaned_data["force_shutdown"]:
        site_title = ApplicationCustomization.get("site_title")
        dictionary["message"] = format_html(
            '<ul class="errorlist"><li>{}</li></ul>'.format(
                f"Tool control is only available on campus. When creating a task, you can't force a tool shutdown while using {site_title} off campus.",
            )
        )
        dictionary["form"] = form
        return render(request, "kiosk/tool_report_problem.html", dictionary)

    task = form.save()
    task.estimated_resolution_time = estimated_resolution_time

    save_task(request, task, customer)

    return redirect("kiosk_tool_information", tool_id=tool.id, user_id=customer.id, back=back)


@login_required
@permission_required("NEMO.kiosk")
@require_POST
def tool_post_comment(request, tool_id, user_id, back):
    tool = Tool.objects.get(id=tool_id, visible=True)
    customer = User.objects.get(id=user_id)

    dictionary = {
        "tool": tool,
        "date": None,
        "customer": customer,
        "back": back,
    }

    return render(request, "kiosk/tool_post_comment.html", dictionary)


@login_required
@permission_required("NEMO.kiosk")
@require_POST
def post_comment(request):
    tool = Tool.objects.get(id=request.POST["tool"])
    customer = User.objects.get(id=request.POST["customer_id"])
    back = request.POST["back"]

    dictionary = {"back": back, "tool": tool, "customer": customer}

    """ Post a comment for a tool. """
    form = CommentForm(request.POST)
    if not form.is_valid():
        dictionary["message"] = nice_errors(form).as_ul()
        dictionary["form"] = form

        return render(request, "kiosk/tool_post_comment.html", dictionary)

    save_comment(customer, form)

    return redirect("kiosk_tool_information", tool_id=tool.id, user_id=customer.id, back=back)


def get_categories_and_tools_dictionary(customer: User, categories=None, tool_names=None) -> Dict:
    tools = Tool.objects.filter(visible=True)
    tool_in_category_filter = Q()  # filter for tools displayed at this root level
    if tool_names:
        # We are displaying selected tools at the root level
        for tool_name in tool_names:
            tool_in_category_filter |= Q(name__iexact=tool_name)
    if categories:
        category_filter = Q()
        for category in categories:
            tool_in_category_filter |= Q(_category__iexact=category)
            category_filter |= Q(_category__istartswith=category + "/")
        tools = tools.filter(category_filter)
    if tool_names and not categories:
        tool_categories = []
    else:
        tool_categories = [t[0] for t in tools.order_by("_category").values_list("_category").distinct()]
    tool_ids_user_is_qualified = remove_duplicates(
        list(customer.qualifications.all().values_list("id", flat=True))
        + list(customer.staff_for_tools.all().values_list("id", flat=True))
    )
    unqualified_categories = [
        category
        for category in tool_categories
        if not customer.is_staff
        and not Tool.objects.filter(visible=True, _category=category, id__in=tool_ids_user_is_qualified).exists()
    ]
    tools_in_this_category = (
        list(Tool.objects.filter(visible=True).filter(tool_in_category_filter)) if tool_in_category_filter else []
    )
    return {
        "selected_category": categories[0] if categories and len(categories) == 1 else None,
        "categories": tool_categories,
        "unqualified_categories": unqualified_categories,
        "tools": tools_in_this_category,
        "unqualified_tools": [
            tool
            for tool in tools_in_this_category
            if not customer.is_staff and tool.id not in tool_ids_user_is_qualified
        ],
    }


@login_required
@permission_required("NEMO.kiosk")
@require_GET
def get_projects_for_consumables(request):
    # Only return project for which consumable withdrawals are allowed
    return get_projects(request, Q(allow_consumable_withdrawals=True))


@login_required
@permission_required("NEMO.kiosk")
@require_http_methods(["GET", "POST"])
def checkout(request, customer_id):
    user: User = User.objects.get(pk=customer_id)
    if not consumable_permissions(user):
        return HttpResponseForbidden("You do not have permission to access consumables.")

    is_self_checkout = self_checkout(user)
    if request.method == "GET":
        from NEMO.rates import rate_class

        rate_dict = rate_class.get_consumable_rates(Consumable.objects.all())
        consumable_list = Consumable.objects.filter(visible=True).order_by("category", "name")
        if is_self_checkout:
            consumable_list = consumable_list.filter(allow_self_checkout=True).filter(
                Q(self_checkout_only_users__isnull=True) | Q(self_checkout_only_users__in=[user])
            )

        dictionary = {
            "customer": user,
            "users": User.objects.filter(is_active=True),
            "consumables": consumable_list,
            "rates": rate_dict,
            "self_checkout": is_self_checkout,
        }
        if is_self_checkout:
            dictionary["projects"] = user.active_projects().filter(allow_consumable_withdrawals=True)

        return render(request, "kiosk/consumables.html", dictionary)
    elif request.method == "POST":
        updated_post_data = request.POST.copy()
        if is_self_checkout:
            updated_post_data.update({"customer": user.id})
        form = ConsumableWithdrawForm(updated_post_data)
        if form.is_valid():
            withdraw = form.save(commit=False)
            customer_allowed = (
                not withdraw.consumable.self_checkout_only_users.exists()
                or withdraw.customer in withdraw.consumable.self_checkout_only_users.all()
            )
            if is_self_checkout and (not withdraw.consumable.allow_self_checkout or not customer_allowed):
                return HttpResponseBadRequest("You can not self checkout this consumable")
            try:
                policy.check_billing_to_project(withdraw.project, withdraw.customer, withdraw.consumable, withdraw)
            except ProjectChargeException as e:
                return HttpResponseBadRequest(e.msg)
            add_withdraw_to_session(request, user.id, withdraw)
        else:
            return HttpResponseBadRequest(nice_errors(form).as_ul())
        return render(
            request,
            "kiosk/consumables_order.html",
            {
                "customer": user,
            },
        )
    else:
        return HttpResponseBadRequest("Invalid Request")


def add_withdraw_to_session(request, customer_id, withdrawal: ConsumableWithdraw):
    request.session.setdefault("kiosk_withdrawals", {})
    customer_id_key = str(customer_id)
    withdrawals: dict = request.session.get("kiosk_withdrawals")
    if withdrawals is not None:
        if customer_id_key not in withdrawals:
            withdrawals[customer_id_key] = []
        withdrawal_dict = {
            "customer": str(withdrawal.customer),
            "customer_id": withdrawal.customer_id,
            "consumable": str(withdrawal.consumable),
            "consumable_id": withdrawal.consumable_id,
            "project": str(withdrawal.project),
            "project_id": withdrawal.project_id,
            "quantity": withdrawal.quantity,
        }
        withdrawals[customer_id_key].append(withdrawal_dict)
    request.session["kiosk_withdrawals"] = withdrawals


def get_customer_cart(request, customer_id: str) -> List:
    withdrawals: List = request.session.get("kiosk_withdrawals", {}).get(str(customer_id), [])
    return withdrawals


@login_required
@permission_required("NEMO.kiosk")
@require_POST
def remove_withdraw_at_index(request):
    try:
        customer_id = request.POST["customer_id"]
        user: User = User.objects.get(pk=customer_id)
        if not consumable_permissions(user):
            return HttpResponseForbidden("You do not have permission to access consumables.")

        index = int(request.POST["index"])
        withdrawals: List = get_customer_cart(request, customer_id)
        if withdrawals:
            del withdrawals[index]
            request.session["kiosk_withdrawals"][customer_id] = withdrawals
        return render(
            request,
            "kiosk/consumables_order.html",
            {
                "customer": user,
            },
        )
    except Exception:
        return HttpResponseBadRequest("Invalid Request")


@login_required
@permission_required("NEMO.kiosk")
@require_POST
def clear_withdrawals(request):
    try:
        customer_id = request.POST["customer_id"]
        user: User = User.objects.get(pk=customer_id)
        if not consumable_permissions(user):
            return HttpResponseForbidden("You do not have permission to access consumables.")

        if "kiosk_withdrawals" in request.session and customer_id in request.session["kiosk_withdrawals"]:
            del request.session["kiosk_withdrawals"][customer_id]
        return render(
            request,
            "kiosk/consumables_order.html",
            {
                "customer": user,
            },
        )
    except Exception:
        return HttpResponseBadRequest("Invalid Request")


@login_required
@permission_required("NEMO.kiosk")
@require_POST
def make_withdrawals(request):
    customer_id = request.POST["customer_id"]
    user: User = User.objects.get(pk=customer_id)
    if not consumable_permissions(user):
        return HttpResponseForbidden("You do not have permission to access consumables.")

    withdrawals: List = get_customer_cart(request, customer_id)
    force_customer = user.id if self_checkout(user) else None
    try:
        with transaction.atomic():
            success_messages = []
            for withdraw in withdrawals:
                withdrawal = make_withdrawal(
                    consumable_id=withdraw["consumable_id"],
                    merchant=user,
                    customer_id=force_customer or withdraw["customer_id"],
                    quantity=withdraw["quantity"],
                    project_id=withdraw["project_id"],
                )
                success_messages.append(make_withdrawal_success_message(withdrawal, user))

            if "kiosk_withdrawals" in request.session and customer_id in request.session["kiosk_withdrawals"]:
                del request.session["kiosk_withdrawals"][customer_id]
            message = "<br>".join(success_messages)
            return render(
                request,
                "kiosk/acknowledgement.html",
                {"message": message, "delay": 10, "badge_number": user.badge_number},
            )
    except ValidationError as e:
        return HttpResponseBadRequest(nice_errors(e).as_ul())
    except Exception:
        return HttpResponseBadRequest("An error occurred while processing the withdrawals.")
