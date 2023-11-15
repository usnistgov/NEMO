from datetime import datetime, timedelta
from http import HTTPStatus

from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import render
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_time
from django.views.decorators.http import require_GET, require_POST

from NEMO.decorators import synchronized
from NEMO.exceptions import RequiredUnansweredQuestionsException
from NEMO.models import BadgeReader, Project, Reservation, ReservationItemType, Tool, UsageEvent, User
from NEMO.policy import policy_class as policy
from NEMO.utilities import localize, quiet_int
from NEMO.views.calendar import (
    cancel_the_reservation,
    extract_configuration,
    extract_reservation_questions,
    render_reservation_questions,
    shorten_reservation,
)
from NEMO.views.customization import ApplicationCustomization
from NEMO.views.status_dashboard import create_tool_summary
from NEMO.views.tool_control import (
    email_managers_required_questions_disable_tool,
    interlock_bypass_allowed,
    interlock_error,
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
    new_usage_event.save()

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
    customer = User.objects.get(id=request.POST["customer_id"])
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
        dynamic_form.charge_for_consumables(current_usage_event, request)
    except Exception as e:
        dictionary = {"message": str(e), "delay": 10}
        return render(request, "kiosk/acknowledgement.html", dictionary)
    dynamic_form.update_tool_counters(current_usage_event.run_data, tool.id)

    current_usage_event.save()
    dictionary = {"message": "You are no longer using the {}".format(tool), "badge_number": customer.badge_number}
    return render(request, "kiosk/acknowledgement.html", dictionary)


@login_required
@permission_required("NEMO.kiosk")
@require_POST
def reserve_tool(request):
    tool = Tool.objects.get(id=request.POST["tool_id"])
    customer = User.objects.get(id=request.POST["customer_id"])
    project = Project.objects.get(id=request.POST["project_id"])
    back = request.POST["back"]

    error_dictionary = {"back": back, "tool": tool, "project": project, "customer": customer}

    """ Create a reservation for a user. """
    try:
        date = parse_date(request.POST["date"])
        start = localize(datetime.combine(date, parse_time(request.POST["start"])))
        end = localize(datetime.combine(date, parse_time(request.POST["end"])))
    except:
        error_dictionary["message"] = "Please enter a valid date, start time, and end time for the reservation."
        return render(request, "kiosk/error.html", error_dictionary)
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
        error_dictionary["message"] = policy_problems[0]
        return render(request, "kiosk/error.html", error_dictionary)

    # All policy checks have passed.
    if project is None and not customer.is_staff:
        error_dictionary["message"] = "You must specify a project for your reservation"
        return render(request, "kiosk/error.html", error_dictionary)

    reservation.additional_information, reservation.self_configuration = extract_configuration(request)
    # Reservation can't be short notice if the user is configuring the tool themselves.
    if reservation.self_configuration:
        reservation.short_notice = False

    # Reservation questions if applicable
    try:
        reservation.question_data = extract_reservation_questions(
            request, ReservationItemType.TOOL, tool.id, reservation.project
        )
    except RequiredUnansweredQuestionsException as e:
        error_dictionary["message"] = str(e)
        return render(request, "kiosk/error.html", error_dictionary)

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

    dictionary = tool.get_configuration_information(user=customer, start=None)
    dictionary["tool"] = tool
    dictionary["date"] = None
    dictionary["project"] = project
    dictionary["customer"] = customer
    dictionary["back"] = back
    dictionary["tool_reservation_times"] = list(
        Reservation.objects.filter(cancelled=False, missed=False, shortened=False, tool=tool, start__gte=timezone.now())
    )

    # Reservation questions if applicable
    dictionary["reservation_questions"] = render_reservation_questions(ReservationItemType.TOOL, tool_id, project, True)

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
        "tool_summary": create_tool_summary(),
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
        "tool_summary": create_tool_summary(),
    }
    return render(request, "kiosk/category_choices.html", dictionary)


@login_required
@permission_required("NEMO.kiosk")
@require_GET
def tool_information(request, tool_id, user_id, back):
    tool = Tool.objects.get(id=tool_id, visible=True)
    customer = User.objects.get(id=user_id)
    dictionary = {
        "customer": customer,
        "tool": tool,
        "rendered_configuration_html": tool.configuration_widget(customer),
        "post_usage_questions": DynamicForm(tool.post_usage_questions).render(
            "tool_usage_group_question", tool.id, virtual_inputs=True
        ),
        "back": back,
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


def get_badge_reader(request) -> BadgeReader:
    reader_id = request.GET.get("reader_id") or ApplicationCustomization.get_int("default_badge_reader_id")
    try:
        badge_reader = BadgeReader.objects.get(id=reader_id)
    except BadgeReader.DoesNotExist:
        badge_reader = BadgeReader.default()
    return badge_reader
