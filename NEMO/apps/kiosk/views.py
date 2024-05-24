from datetime import datetime, timedelta
from http import HTTPStatus

from django.conf import settings
from django.contrib.auth.decorators import login_required, permission_required
from django.db.models import Q
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_time
from django.utils.html import format_html
from django.views.decorators.http import require_GET, require_POST

from NEMO.decorators import synchronized
from NEMO.exceptions import RequiredUnansweredQuestionsException
from NEMO.forms import CommentForm, TaskForm, nice_errors
from NEMO.models import (
    BadgeReader,
    Project,
    Reservation,
    ReservationItemType,
    TaskCategory,
    TaskStatus,
    Tool,
    ToolWaitList,
    UsageEvent,
    User,
)
from NEMO.policy import policy_class as policy
from NEMO.utilities import localize, quiet_int
from NEMO.views.area_access import log_out_user
from NEMO.views.calendar import (
    cancel_the_reservation,
    extract_reservation_questions,
    render_reservation_questions,
    set_reservation_configuration,
    shorten_reservation,
)
from NEMO.views.customization import ApplicationCustomization, ToolCustomization
from NEMO.views.tasks import save_task
from NEMO.views.tool_control import (
    email_managers_required_questions_disable_tool,
    interlock_bypass_allowed,
    interlock_error,
    save_comment,
)
from NEMO.widgets.dynamic_form import DynamicForm


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
        if bypass_interlock and interlock_bypass_allowed(customer):
            pass
        else:
            return interlock_error("Enable", customer)

    # Create a new usage event to track how long the user uses the tool.
    new_usage_event = UsageEvent()
    new_usage_event.operator = customer
    new_usage_event.user = customer
    new_usage_event.project = project
    new_usage_event.tool = tool

    # Collect post-usage questions
    dynamic_form = DynamicForm(tool.pre_usage_questions)

    try:
        new_usage_event.pre_run_data = dynamic_form.extract(request)
    except RequiredUnansweredQuestionsException as e:
        dictionary = {"message": str(e), "delay": 10}
        return render(request, "kiosk/acknowledgement.html", dictionary)
    new_usage_event.save()

    # Remove wait list entry if it exists
    wait_list_entry = ToolWaitList.objects.filter(tool=tool, expired=False, deleted=False, user=customer)
    if wait_list_entry.count() > 0:
        wait_list_entry.update(deleted=True, date_exited=timezone.now())

    try:
        dynamic_form.charge_for_consumables(new_usage_event, new_usage_event.pre_run_data, request)
    except Exception as e:
        dictionary = {"message": str(e), "delay": 10}
        return render(request, "kiosk/acknowledgement.html", dictionary)
    dynamic_form.update_tool_counters(new_usage_event.pre_run_data, tool.id)

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
        if bypass_interlock and interlock_bypass_allowed(customer):
            pass
        else:
            return interlock_error("Disable", customer)

    # Shorten the user's tool reservation since we are now done using the tool
    current_usage_event = tool.get_current_usage_event()
    staff_shortening = request.POST.get("shorten", False)
    shorten_reservation(
        user=current_usage_event.user, item=tool, new_end=timezone.now() + downtime, force=staff_shortening
    )

    # End the current usage event for the tool and save it.
    current_usage_event.end = timezone.now() + downtime

    # Collect post-usage questions
    dynamic_form = DynamicForm(tool.post_usage_questions)

    try:
        current_usage_event.run_data = dynamic_form.extract(request)
    except RequiredUnansweredQuestionsException as e:
        if customer.is_staff and customer != current_usage_event.operator and current_usage_event.user != customer:
            # if a staff is forcing somebody off the tool and there are required questions, send an email and proceed
            current_usage_event.run_data = e.run_data
            email_managers_required_questions_disable_tool(current_usage_event.operator, customer, tool, e.questions)
        else:
            dictionary = {"message": str(e), "delay": 10}
            return render(request, "kiosk/acknowledgement.html", dictionary)

    try:
        dynamic_form.charge_for_consumables(current_usage_event, current_usage_event.run_data, request)
    except Exception as e:
        dictionary = {"message": str(e), "delay": 10}
        return render(request, "kiosk/acknowledgement.html", dictionary)
    dynamic_form.update_tool_counters(current_usage_event.run_data, tool.id)

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

    # The user must be qualified to use the tool itself, or the parent tool in case of alternate tool.
    tool_to_check_qualifications = tool.parent_tool if tool.is_child_tool() else tool
    if tool_to_check_qualifications not in customer.qualifications.all() and not customer.is_staff:
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
    tool = Tool.objects.get(id=request.POST["tool_id"])
    customer = User.objects.get(id=request.POST["customer_id"])
    project = Project.objects.get(id=request.POST["project_id"])
    back = request.POST["back"]

    dictionary = {"back": back, "tool": tool, "project": project, "customer": customer}

    """ Create a reservation for a user. """
    try:
        date = parse_date(request.POST["date"])
        start = localize(datetime.combine(date, parse_time(request.POST["start"])))
        end = localize(datetime.combine(date, parse_time(request.POST["end"])))
    except:
        dictionary["message"] = "Please enter a valid date, start time, and end time for the reservation."
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
    if project is None and not customer.is_staff:
        dictionary["message"] = "You must specify a project for your reservation"
        return render(request, "kiosk/error.html", dictionary)

    reservation_questions = render_reservation_questions(ReservationItemType.TOOL, tool.id, reservation.project, True)
    tool_config = tool.is_configurable()
    needs_extra_config = reservation_questions or tool_config
    if needs_extra_config and not request.POST.get("configured") == "true":
        dictionary.update(tool.get_configuration_information(user=customer, start=reservation.start))
        dictionary.update(
            {
                "request_date": request.POST["date"],
                "request_start": request.POST["start"],
                "request_end": request.POST["end"],
                "reservation": reservation,
                "reservation_questions": reservation_questions,
            }
        )
        return render(request, "kiosk/tool_reservation_extra.html", dictionary)

    set_reservation_configuration(reservation, request)
    # Reservation can't be short notice if the user is configuring the tool themselves.
    if reservation.self_configuration:
        reservation.short_notice = False

    # Reservation questions if applicable
    try:
        reservation.question_data = extract_reservation_questions(
            request, ReservationItemType.TOOL, tool.id, reservation.project
        )
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

    categories = [
        t[0] for t in Tool.objects.filter(visible=True).order_by("_category").values_list("_category").distinct()
    ]
    unqualified_categories = [
        category
        for category in categories
        if not customer.is_staff
        and not Tool.objects.filter(
            visible=True, _category=category, id__in=customer.qualifications.all().values_list("id")
        ).exists()
    ]
    dictionary = {
        "now": timezone.now(),
        "customer": customer,
        "usage_events": list(usage_events),
        "upcoming_reservations": tool_reservations,
        "categories": categories,
        "unqualified_categories": unqualified_categories,
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
    tools = Tool.objects.filter(visible=True, _category=category)
    dictionary = {
        "customer": customer,
        "category": category,
        "tools": tools,
        "unqualified_tools": [
            tool for tool in tools if not customer.is_staff and tool not in customer.qualifications.all()
        ],
    }
    return render(request, "kiosk/category_choices.html", dictionary)


@login_required
@permission_required("NEMO.kiosk")
@require_GET
def tool_information(request, tool_id, user_id, back):
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
        customer.is_staff or customer.is_facility_manager
    ):
        if customer.is_facility_manager:
            tool_credentials = tool.toolcredentials_set.all()
        else:
            tool_credentials = tool.toolcredentials_set.filter(
                Q(authorized_staff__isnull=True) | Q(authorized_staff__in=[customer])
            )
    dictionary = {
        "customer": customer,
        "tool": tool,
        "tool_credentials": tool_credentials,
        "rendered_configuration_html": tool.configuration_widget(customer),
        "pre_usage_questions": DynamicForm(tool.pre_usage_questions).render(
            "tool_usage_group_question", tool.id, virtual_inputs=True
        ),
        "post_usage_questions": DynamicForm(tool.post_usage_questions).render(
            "tool_usage_group_question", tool.id, virtual_inputs=True
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
    try:
        current_reservation = Reservation.objects.get(
            start__lt=timezone.now(),
            end__gt=timezone.now(),
            cancelled=False,
            missed=False,
            shortened=False,
            user=customer,
            tool=tool,
        )
        remaining_reservation_duration = int((current_reservation.end - timezone.now()).total_seconds() / 60)
        # We don't need to bother telling the user their reservation will be shortened if there's less than two minutes left.
        # Staff are exempt from reservation shortening.
        if remaining_reservation_duration > 2:
            dictionary["remaining_reservation_duration"] = remaining_reservation_duration
    except Reservation.DoesNotExist:
        pass
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
        "date": None,
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
