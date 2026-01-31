import json
import re
from datetime import datetime, timedelta
from http import HTTPStatus
from logging import getLogger
from typing import Optional, Tuple, Union

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden, HttpResponseNotFound, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.timezone import make_aware
from django.views.decorators.http import require_GET, require_POST

from NEMO.constants import ADDITIONAL_INFORMATION_MAXIMUM_LENGTH
from NEMO.decorators import disable_session_expiry_refresh, postpone, staff_member_or_tool_staff_required, synchronized
from NEMO.exceptions import ProjectChargeException, RequiredUnansweredQuestionsException
from NEMO.forms import ScheduledOutageForm, save_scheduled_outage
from NEMO.models import (
    Area,
    AreaAccessRecord,
    Configuration,
    ConfigurationOption,
    Project,
    Reservation,
    ReservationItemType,
    ScheduledOutage,
    ScheduledOutageCategory,
    Tool,
    UsageEvent,
    User,
    UserCalendarToolList,
    UserPreferences,
)
from NEMO.policy import check_maximum_users_in_overlapping_reservations, policy_class as policy
from NEMO.utilities import (
    RecurrenceFrequency,
    bootstrap_primary_color,
    create_ics,
    datetime_input_format,
    distinct_qs_value_list,
    extract_times,
    format_datetime,
    get_email_from_settings,
    get_full_url,
    localize,
    parse_parameter_string,
    render_email_template,
    send_mail,
)
from NEMO.views.customization import (
    ApplicationCustomization,
    CalendarCustomization,
    EmailsCustomization,
    ToolCustomization,
    get_media_file_contents,
)

calendar_logger = getLogger(__name__)


@login_required
@require_GET
def calendar(request, item_type=None, item_id=None):
    """Present the calendar view to the user."""
    user: User = request.user
    if request.device == "mobile":
        if item_type and item_type == "tool" and item_id:
            return redirect("view_calendar", "tool", item_id)
        else:
            return redirect("choose_item", "view_calendar")

    tools = Tool.objects.filter(visible=True).only("name", "_category", "parent_tool_id").order_by("_category", "name")
    areas = Area.objects.filter(requires_reservation=True).only("name")

    # We want to remove areas the user doesn't have access to
    display_all_areas = CalendarCustomization.get_bool("calendar_display_not_qualified_areas")
    if not display_all_areas and areas and user and not user.is_superuser:
        areas = [area for area in areas if area in user.accessible_areas()]

    from NEMO.widgets.item_tree import ItemTree

    rendered_item_tree_html = ItemTree().render(None, {"tools": tools, "areas": areas, "user": request.user})

    calendar_view = CalendarCustomization.get("calendar_view")
    calendar_first_day_of_week = CalendarCustomization.get("calendar_first_day_of_week")
    calendar_axis_time_format = CalendarCustomization.get("calendar_axis_time_format")
    calendar_day_column_format = CalendarCustomization.get("calendar_day_column_format")
    calendar_day_time_format = CalendarCustomization.get("calendar_day_time_format")
    calendar_week_column_format = CalendarCustomization.get("calendar_week_column_format")
    calendar_week_time_format = CalendarCustomization.get("calendar_week_time_format")
    calendar_month_column_format = CalendarCustomization.get("calendar_month_column_format")
    calendar_month_time_format = CalendarCustomization.get("calendar_month_time_format")
    calendar_start_of_the_day = CalendarCustomization.get("calendar_start_of_the_day")
    calendar_now_indicator = CalendarCustomization.get("calendar_now_indicator")
    calendar_all_tools = CalendarCustomization.get("calendar_all_tools")
    calendar_all_areas = CalendarCustomization.get("calendar_all_areas")
    calendar_all_areastools = CalendarCustomization.get("calendar_all_areastools")

    # Create reservation confirmation setting
    create_reservation_confirmation_default = CalendarCustomization.get_bool("create_reservation_confirmation")
    create_reservation_confirmation_override = user.get_preferences().create_reservation_confirmation_override
    create_reservation_confirmation = create_reservation_confirmation_default ^ create_reservation_confirmation_override

    # Change reservation confirmation setting
    change_reservation_confirmation_default = CalendarCustomization.get_bool("change_reservation_confirmation")
    change_reservation_confirmation_override = user.get_preferences().change_reservation_confirmation_override
    change_reservation_confirmation = change_reservation_confirmation_default ^ change_reservation_confirmation_override

    # Reservation confirmation date and time settings
    reservation_confirmation_date_format = CalendarCustomization.get("reservation_confirmation_date_format")
    reservation_confirmation_time_format = CalendarCustomization.get("reservation_confirmation_time_format")

    dictionary = {
        "rendered_item_tree_html": rendered_item_tree_html,
        "tools": list(tools),
        "areas": list(areas),
        "auto_select_item_id": item_id,
        "auto_select_item_type": item_type,
        "calendar_view": calendar_view,
        "calendar_first_day_of_week": calendar_first_day_of_week,
        "calendar_axis_time_format": calendar_axis_time_format,
        "calendar_day_column_format": calendar_day_column_format,
        "calendar_day_time_format": calendar_day_time_format,
        "calendar_week_column_format": calendar_week_column_format,
        "calendar_week_time_format": calendar_week_time_format,
        "calendar_month_column_format": calendar_month_column_format,
        "calendar_month_time_format": calendar_month_time_format,
        "calendar_start_of_the_day": calendar_start_of_the_day,
        "calendar_now_indicator": calendar_now_indicator,
        "calendar_all_tools": calendar_all_tools,
        "calendar_all_areas": calendar_all_areas,
        "calendar_all_areastools": calendar_all_areastools,
        "calendar_user_tool_lists": UserCalendarToolList.objects.filter(user=user),
        "create_reservation_confirmation": create_reservation_confirmation,
        "change_reservation_confirmation": change_reservation_confirmation,
        "reservation_confirmation_date_format": reservation_confirmation_date_format,
        "reservation_confirmation_time_format": reservation_confirmation_time_format,
        "self_login": False,
        "self_logout": False,
    }
    login_logout = ApplicationCustomization.get_bool("calendar_login_logout", raise_exception=False)
    self_login = ApplicationCustomization.get_bool("self_log_in", raise_exception=False)
    self_logout = ApplicationCustomization.get_bool("self_log_out", raise_exception=False)
    if login_logout:
        dictionary["self_login"] = self_login
        dictionary["self_logout"] = self_logout
    if request.user.is_staff:
        dictionary["users"] = User.objects.all()
    return render(request, "calendar/calendar.html", dictionary)


@login_required
@require_GET
@disable_session_expiry_refresh
def event_feed(request):
    """Get all reservations for a specific time-window. Optionally: filter by tool, area or user."""
    try:
        start, end = extract_calendar_dates(request.GET)
    except Exception as e:
        return HttpResponseBadRequest("Invalid start or end time. " + str(e))

    # We don't want to let someone hammer the database with phony calendar feed lookups.
    # Block any requests that have a duration of more than 8 weeks. The FullCalendar
    # should only ever request 6 weeks of data at a time (at most).
    if end - start > timedelta(weeks=8):
        return HttpResponseBadRequest("Calendar feed request has too long a duration: " + str(end - start))

    event_type = request.GET.get("event_type")

    facility_name = ApplicationCustomization.get("facility_name")
    if event_type == "reservations":
        return reservation_event_feed(request, start, end)
    if event_type == "reservations and use":
        reservation_feed = json.loads(reservation_event_feed(request, start, end).content)
        usage_feed = json.loads(usage_event_feed(request, start, end).content)
        return JsonResponse(reservation_feed + usage_feed, safe=False)
    elif event_type == f"{facility_name.lower()} use":
        return usage_event_feed(request, start, end)
    # Only staff may request a specific user's history...
    elif event_type == "specific user" and request.user.is_staff:
        user = get_object_or_404(User, id=request.GET.get("user"))
        return specific_user_feed(request, user, start, end)
    elif event_type == "configuration agenda":
        return configuration_agenda_event_feed(request, start, end)
    else:
        return HttpResponseBadRequest("Invalid event type or operation not authorized.")


def extract_calendar_dates(parameters):
    """
    Extract the "start" and "end" parameters for FullCalendar's specific date format while performing a few logic validation checks.
    """
    full_calendar_date_format = "%Y-%m-%d"
    try:
        start = parameters["start"]
    except:
        raise Exception("The request parameters did not contain a start time.")

    try:
        end = parameters["end"]
    except:
        raise Exception("The request parameters did not contain an end time.")

    try:
        start = localize(datetime.strptime(start, full_calendar_date_format))
    except:
        raise Exception("The request parameters did not have a valid start time.")

    try:
        end = localize(datetime.strptime(end, full_calendar_date_format))
    except:
        raise Exception("The request parameters did not have a valid end time.")

    if end < start:
        raise Exception("The request parameters have an end time that precedes the start time.")

    return start, end


def reservation_event_feed(request, start, end):
    events = Reservation.objects.filter(cancelled=False, missed=False, shortened=False)
    outages = ScheduledOutage.objects.none()
    # Exclude events for which the following is true:
    # The event starts and ends before the time-window, and...
    # The event starts and ends after the time-window.
    events = events.exclude(start__lt=start, end__lt=start)
    events = events.exclude(start__gt=end, end__gt=end)
    all_tools = request.GET.get("all_tools")
    all_areas = request.GET.get("all_areas")
    all_areastools = request.GET.get("all_areastools")
    display_name = request.GET.get("display_name") == "true"

    # Filter events that only have to do with the relevant tool/area.
    item_type = request.GET.get("item_type")
    if all_tools:
        events = events.filter(area=None)
    elif all_areas:
        events = events.filter(tool=None)
    if item_type:
        item_type = ReservationItemType(item_type)
        item_id = request.GET.get("item_id")
        if item_id and not (all_tools or all_areas or all_areastools):
            events = events.filter(**{f"{item_type.value}__id": item_id})
            if item_type == ReservationItemType.TOOL:
                outages = ScheduledOutage.objects.filter(
                    Q(tool=item_id) | Q(resource__fully_dependent_tools__in=[item_id])
                )
            elif item_type == ReservationItemType.AREA:
                outages = Area.objects.get(pk=item_id).scheduled_outage_queryset()

    # Exclude outages for which the following is true:
    # The outage starts and ends before the time-window, and...
    # The outage starts and ends after the time-window.
    outages = outages.exclude(start__lt=start, end__lt=start)
    outages = outages.exclude(start__gt=end, end__gt=end)

    # Filter events that only have to do with the current user.
    personal_schedule = request.GET.get("personal_schedule")
    if personal_schedule:
        events = events.filter(user=request.user)

    dictionary = {
        "events": events,
        "outages": outages,
        "personal_schedule": personal_schedule,
        "all_tools": all_tools,
        "all_areas": all_areas,
        "all_areastools": all_areastools,
        "display_name": display_name,
        "display_configuration": CalendarCustomization.get_bool("calendar_configuration_in_reservations"),
    }
    return render(request, "calendar/reservation_event_feed.html", dictionary)


def usage_event_feed(request, start, end):
    usage_events = UsageEvent.objects.none()
    area_access_events = AreaAccessRecord.objects.none()
    missed_reservations = Reservation.objects.none()

    item_id = request.GET.get("item_id")
    item_type = ReservationItemType(request.GET.get("item_type")) if request.GET.get("item_type") else None

    personal_schedule = request.GET.get("personal_schedule")
    all_areas = request.GET.get("all_areas")
    all_tools = request.GET.get("all_tools")
    all_areastools = request.GET.get("all_areastools")

    if personal_schedule:
        # Filter events that only have to do with the current user.
        # Display missed reservations, tool and area usage when 'personal schedule' is selected
        usage_events = UsageEvent.objects.filter(user=request.user)
        area_access_events = AreaAccessRecord.objects.filter(customer=request.user)
        missed_reservations = Reservation.objects.filter(missed=True, user=request.user)
    elif all_areas:
        area_access_events = AreaAccessRecord.objects.filter()
        missed_reservations = Reservation.objects.filter(missed=True, tool=None)
    elif all_tools:
        usage_events = UsageEvent.objects.filter()
        missed_reservations = Reservation.objects.filter(missed=True, area=None)
    elif all_areastools:
        usage_events = UsageEvent.objects.all()
        area_access_events = AreaAccessRecord.objects.filter()
        missed_reservations = Reservation.objects.filter(missed=True)
    elif item_type:
        reservation_filter = {item_type.value: item_id}
        missed_reservations = Reservation.objects.filter(missed=True).filter(**reservation_filter)
        # Filter events that only have to do with the relevant tool or area.
        if item_id and item_type == ReservationItemType.TOOL:
            usage_events = UsageEvent.objects.filter(tool__id__in=Tool.objects.get(pk=item_id).get_family_tool_ids())
        if item_id and item_type == ReservationItemType.AREA:
            area_access_events = AreaAccessRecord.objects.filter(area__id=item_id)

    # Exclude events for which the following is true:
    # The event starts and ends before the time-window, and...
    # The event starts and ends after the time-window.
    usage_events = usage_events.exclude(start__lt=start, end__lt=start)
    usage_events = usage_events.exclude(start__gt=end, end__gt=end)
    area_access_events = area_access_events.exclude(start__lt=start, end__lt=start)
    area_access_events = area_access_events.exclude(start__gt=end, end__gt=end)
    missed_reservations = missed_reservations.exclude(start__lt=start, end__lt=start)
    missed_reservations = missed_reservations.exclude(start__gt=end, end__gt=end)

    dictionary = {
        "usage_events": usage_events,
        "area_access_events": area_access_events,
        "personal_schedule": personal_schedule,
        "missed_reservations": missed_reservations,
        "all_tools": all_tools,
        "all_areas": all_areas,
        "all_areastools": all_areastools,
    }
    return render(request, "calendar/usage_event_feed.html", dictionary)


def specific_user_feed(request, user, start, end):
    # Find all tool usage events for a user.
    # Exclude events for which the following is true:
    # The event starts and ends before the time-window, and...
    # The event starts and ends after the time-window.
    usage_events = UsageEvent.objects.filter(user=user)
    usage_events = usage_events.exclude(start__lt=start, end__lt=start)
    usage_events = usage_events.exclude(start__gt=end, end__gt=end)

    # Find all area access events for a user.
    area_access_events = AreaAccessRecord.objects.filter(customer=user)
    area_access_events = area_access_events.exclude(start__lt=start, end__lt=start)
    area_access_events = area_access_events.exclude(start__gt=end, end__gt=end)

    # Find all reservations for the user that were not missed or cancelled.
    reservations = Reservation.objects.filter(user=user, missed=False, cancelled=False, shortened=False)
    reservations = reservations.exclude(start__lt=start, end__lt=start)
    reservations = reservations.exclude(start__gt=end, end__gt=end)

    # Find all missed reservations for the user.
    missed_reservations = Reservation.objects.filter(user=user, missed=True)
    missed_reservations = missed_reservations.exclude(start__lt=start, end__lt=start)
    missed_reservations = missed_reservations.exclude(start__gt=end, end__gt=end)

    dictionary = {
        "usage_events": usage_events,
        "area_access_events": area_access_events,
        "reservations": reservations,
        "missed_reservations": missed_reservations,
    }
    return render(request, "calendar/specific_user_feed.html", dictionary)


def configuration_agenda_event_feed(request, start, end):
    events = Reservation.objects.filter(
        cancelled=False, missed=False, shortened=False, configurationoption_set__isnull=False
    ).distinct()
    # Exclude events for which the following is true:
    # The event starts and ends before the time-window, and...
    # The event starts and ends after the time-window.
    events = events.exclude(start__lt=start, end__lt=start)
    events = events.exclude(start__gt=end, end__gt=end)
    all_tools = request.GET.get("all_tools")

    # Filter events that only have to do with the relevant tool/area.
    item_type = request.GET.get("item_type")
    if all_tools:
        events = events.filter(area=None)
    if item_type:
        item_type = ReservationItemType(item_type)
        item_id = request.GET.get("item_id")
        if item_id and not all_tools:
            events = events.filter(**{f"{item_type.value}__id": item_id})

    personal_schedule = request.GET.get("personal_schedule")

    dictionary = {
        "events": events,
        "personal_schedule": personal_schedule,
        "all_tools": all_tools,
    }
    return render(request, "calendar/configuration_event_feed.html", dictionary)


@login_required
@require_POST
def create_reservation(request):
    """Create a reservation for a user."""
    try:
        start, end = extract_times(request.POST)
        item_type = request.POST["item_type"]
        item_id = request.POST.get("item_id")
    except Exception as e:
        return HttpResponseBadRequest(str(e))
    return create_item_reservation(request, request.user, start, end, ReservationItemType(item_type), item_id)


@synchronized("current_user")
def create_item_reservation(request, current_user: User, start, end, item_type: ReservationItemType, item_id):
    item = get_object_or_404(item_type.get_object_class(), id=item_id)
    staff_on_tool = current_user.is_staff_on_tool(item)
    explicit_policy_override = False
    reservation_for_other_error = None
    if not current_user.is_staff and not staff_on_tool and request.POST.get("impersonate"):
        reservation_for_other_error = "You are not allowed to create a reservation for someone else on this tool."
    if current_user.is_staff or staff_on_tool:
        try:
            user = User.objects.get(id=request.POST["impersonate"])
        except:
            user = current_user
        try:
            explicit_policy_override = request.POST["explicit_policy_override"] == "true"
        except:
            pass
    else:
        user = current_user
    # Create the new reservation:
    new_reservation = Reservation()
    new_reservation.user = user
    new_reservation.creator = current_user
    # set tool or area
    setattr(new_reservation, item_type.value, item)
    new_reservation.start = start
    new_reservation.end = end
    new_reservation.short_notice = (
        item.determine_insufficient_notice(start) if item_type == ReservationItemType.TOOL else False
    )
    policy_problems, overridable = policy.check_to_save_reservation(
        cancelled_reservation=None,
        new_reservation=new_reservation,
        user_creating_reservation=current_user,
        explicit_policy_override=explicit_policy_override,
    )
    if reservation_for_other_error:
        policy_problems.append(reservation_for_other_error)

    # If there was a policy problem with the reservation, then return the error...
    if policy_problems:
        return render(
            request,
            "calendar/policy_dialog.html",
            {
                "policy_problems": policy_problems,
                "overridable": overridable and (current_user.is_staff or staff_on_tool),
                "reservation_action": "create",
            },
        )

    # All policy checks have passed.

    # If the user only has one project then associate it with the reservation.
    # Otherwise, present a dialog box for the user to choose which project to associate.
    if not user.is_staff_on_tool(item):
        active_projects = user.active_projects()
        if len(active_projects) == 1:
            new_reservation.project = active_projects[0]
        else:
            try:
                new_reservation.project = Project.objects.get(id=request.POST["project_id"])
            except:
                return render(
                    request,
                    "calendar/project_choice.html",
                    {
                        "active_projects": active_projects,
                        "missed_reservation_threshold": new_reservation.reservation_item.missed_reservation_threshold,
                        "late_cancellation_reservation_threshold": new_reservation.reservation_item.late_cancellation_reservation_threshold,
                    },
                )

        # Check if we are allowed to bill to project
        try:
            policy.check_billing_to_project(
                new_reservation.project, user, new_reservation.reservation_item, new_reservation
            )
        except ProjectChargeException as e:
            policy_problems.append(e.msg)
            return render(
                request,
                "calendar/policy_dialog.html",
                {"policy_problems": policy_problems, "overridable": False, "reservation_action": "create"},
            )

    # Reservation questions if applicable
    dynamic_forms = item.get_reservation_questions(new_reservation.project)
    if dynamic_forms:
        if not bool(request.POST.get("reservation_questions", False)):
            # We have not yet asked the questions
            return render(
                request, "calendar/reservation_questions.html", {"reservation_questions": dynamic_forms.render()}
            )
        else:
            # We already asked before, now we need to extract the results
            try:
                new_reservation.question_data = dynamic_forms.extract(request)
            except RequiredUnansweredQuestionsException as e:
                dictionary = {"error": str(e), "reservation_questions": dynamic_forms.render()}
                return render(request, "calendar/reservation_questions.html", dictionary)

    # Configuration rules only apply to tools
    if item_type == ReservationItemType.TOOL:
        configured = request.POST.get("configured") == "true"
        # If a reservation is requested and the tool does not require configuration...
        if not item.is_configurable():
            new_reservation.save_and_notify()
            return reservation_success(request, new_reservation)

        # If a reservation is requested and the tool requires configuration that has not been submitted...
        elif item.is_configurable() and not configured:
            configuration_information = item.get_configuration_information(user=user, start=start)
            return render(request, "calendar/configuration.html", configuration_information)

        # If a reservation is requested and configuration information is present also...
        elif item.is_configurable() and configured:
            set_reservation_configuration(new_reservation, request)
            # Reservation can't be short notice if the user is configuring the tool themselves.
            if new_reservation.self_configuration:
                new_reservation.short_notice = False
            new_reservation.save_and_notify()
            return reservation_success(request, new_reservation)

    elif item_type == ReservationItemType.AREA:
        new_reservation.save_and_notify()
        return HttpResponse()

    return HttpResponseBadRequest("Reservation creation failed because invalid parameters were sent to the server.")


def reservation_success(request, reservation: Reservation):
    """Checks area capacity and display warning message if capacity is high"""
    max_area_overlap, max_location_overlap = (0, 0)
    max_area_time, max_location_time = (None, None)
    area: Area = (
        reservation.tool.requires_area_access
        if reservation.reservation_item_type == ReservationItemType.TOOL
        else reservation.area
    )
    location = reservation.tool.location if reservation.reservation_item_type == ReservationItemType.TOOL else None
    if area and area.reservation_warning:
        overlapping_reservations_in_same_area = Reservation.objects.filter(
            cancelled=False, missed=False, shortened=False, end__gte=reservation.start, start__lte=reservation.end
        )
        if reservation.reservation_item_type == ReservationItemType.TOOL:
            overlapping_reservations_in_same_area = overlapping_reservations_in_same_area.filter(
                tool__in=Tool.objects.filter(_requires_area_access=area)
            )
        elif reservation.reservation_item_type == ReservationItemType.AREA:
            overlapping_reservations_in_same_area = overlapping_reservations_in_same_area.filter(area=area)
        max_area_overlap, max_area_time = check_maximum_users_in_overlapping_reservations(
            overlapping_reservations_in_same_area
        )
        if location:
            overlapping_reservations_in_same_location = overlapping_reservations_in_same_area.filter(
                tool__in=Tool.objects.filter(_location=location)
            )
            max_location_overlap, max_location_time = check_maximum_users_in_overlapping_reservations(
                overlapping_reservations_in_same_location
            )
    if max_area_overlap and max_area_overlap >= area.warning_capacity():
        dictionary = {
            "area": area,
            "location": location,
            "max_area_count": max_area_overlap,
            "max_location_count": max_location_overlap,
            "max_area_time": max(max_area_time, reservation.start),
            "max_location_time": max(max_location_time, reservation.start) if max_location_time else None,
        }
        return render(
            request, "calendar/reservation_warning.html", dictionary, status=201
        )  # send 201 code CREATED to indicate success but with more information to come
    else:
        return HttpResponse()


def set_reservation_configuration(reservation: Reservation, request):
    configuration_options = []
    for key, value in request.POST.items():
        entry = parse_configuration_entry(reservation, key, value)
        if entry:
            configuration_options.append(entry)
    # Sort by configuration display priority and add config options to the list to save later:
    if configuration_options:
        reservation._deferred_related_models = []
        for config in sorted(configuration_options, key=lambda x: x[0]):
            reservation._deferred_related_models.append(config[1])
    if "additional_information" in request.POST:
        reservation.additional_information = request.POST["additional_information"][
            :ADDITIONAL_INFORMATION_MAXIMUM_LENGTH
        ].strip()
    reservation.self_configuration = True if request.POST.get("self_configuration") == "on" else False


def parse_configuration_entry(reservation: Reservation, key, value) -> Optional[Tuple[int, ConfigurationOption]]:
    if value == "" or not re.match("^configuration_[0-9]+__slot_[0-9]+__display_order_[0-9]+$", key):
        return None
    config_id, slot, display_order = [int(s) for s in key.split("_") if s.isdigit()]
    configuration = Configuration.objects.get(pk=config_id)
    if not configuration.enabled:
        return None
    setting = configuration.get_available_setting(value)

    option_value = ConfigurationOption()
    option_value.current_setting = setting
    option_value.available_settings = configuration.available_settings
    option_value.calendar_colors = configuration.calendar_colors
    option_value.absence_string = configuration.absence_string
    option_value.reservation = reservation
    option_value.configuration = configuration
    if len(configuration.current_settings_as_list()) == 1:
        option_value.name = configuration.configurable_item_name or configuration.name
    else:
        option_value.name = f"{configuration.configurable_item_name or configuration.name} #{str(slot + 1)}"
    return display_order, option_value


@staff_member_or_tool_staff_required
@require_POST
def create_outage(request):
    """Create an outage."""
    try:
        start, end = extract_times(request.POST)
        item_type = ReservationItemType(request.POST["item_type"])
        item_id = request.POST.get("item_id")
    except Exception as e:
        return HttpResponseBadRequest(str(e))
    item = get_object_or_404(item_type.get_object_class(), id=item_id)
    if not request.user.is_staff and not request.user.is_staff_on_tool(item):
        return HttpResponseBadRequest("You are not allowed to create an outage for this tool.")
    # Create the new outage:
    form = ScheduledOutageForm(request.POST)
    if not form.is_valid():
        calendar_outage_recurrence_limit = CalendarCustomization.get("calendar_outage_recurrence_limit")
        dictionary = {
            "form": form,
            "outage_submitted": request.POST.get("outage_submitted"),
            "categories": ScheduledOutageCategory.objects.all(),
            "recurrence_intervals": RecurrenceFrequency.choices(),
            "recurrence_date_start": start.date(),
            "calendar_outage_recurrence_limit": calendar_outage_recurrence_limit,
        }
        return render(request, "calendar/scheduled_outage_information.html", dictionary)

    # If there is a policy problem for the outage then return the error...
    response = save_scheduled_outage(form, request.user, item, start=start, end=end)
    if response and response.status_code != HTTPStatus.OK:
        return response

    return HttpResponse()


@login_required
@require_POST
def resize_reservation(request):
    """Resize a reservation for a user."""
    try:
        delta = timedelta(minutes=int(request.POST["delta"]))
    except:
        return HttpResponseBadRequest("Invalid delta")
    return modify_reservation(request, request.user, None, delta)


@staff_member_or_tool_staff_required
@require_POST
def resize_outage(request):
    """Resize an outage"""
    try:
        delta = timedelta(minutes=int(request.POST["delta"]))
    except:
        return HttpResponseBadRequest("Invalid delta")
    return modify_outage(request, None, delta)


@login_required
@require_POST
def move_reservation(request):
    """Move a reservation for a user."""
    try:
        delta = timedelta(minutes=int(request.POST["delta"]))
    except:
        return HttpResponseBadRequest("Invalid delta")
    return modify_reservation(request, request.user, delta, delta)


@staff_member_or_tool_staff_required
@require_POST
def move_outage(request):
    """Move an outage for a user."""
    try:
        delta = timedelta(minutes=int(request.POST["delta"]))
    except:
        return HttpResponseBadRequest("Invalid delta")
    return modify_outage(request, delta, delta)


@synchronized("current_user")
def modify_reservation(request, current_user, start_delta, end_delta):
    """
    Cancel the user's old reservation and create a new one. Reservations are cancelled and recreated so that
    reservation abuse can be tracked if necessary. This function should be called by other views and should
    not be tied directly to a URL.
    """
    try:
        reservation_to_cancel = Reservation.objects.get(pk=request.POST.get("id"))
    except Reservation.DoesNotExist:
        return HttpResponseNotFound("The reservation that you wish to modify doesn't exist!")
    explicit_policy_override = False
    try:
        explicit_policy_override = request.POST["explicit_policy_override"] == "true"
    except:
        pass
    staff_on_tool = current_user.is_staff_on_tool(reservation_to_cancel.tool)
    # Record the current time so that the timestamp of the cancelled reservation and the new reservation match exactly.
    now = timezone.now()
    # Create a new reservation for the user by copying the original one.
    new_start = reservation_to_cancel.start + start_delta if start_delta else None
    new_end = reservation_to_cancel.end + end_delta if end_delta else None
    new_reservation = reservation_to_cancel.copy(new_start, new_end)
    # Set new creator/time
    new_reservation.creation_time = now
    new_reservation.creator = current_user

    response = policy.check_to_cancel_reservation(current_user, reservation_to_cancel, new_reservation)
    # Do not move the reservation if the user was not authorized to cancel it.
    if response.status_code != HTTPStatus.OK:
        return response

    # Cancel the user's original reservation.
    reservation_to_cancel.cancelled = True
    reservation_to_cancel.cancellation_time = now
    reservation_to_cancel.cancelled_by = current_user

    if reservation_to_cancel.start < new_reservation.start:
        # Only check if it has a different time that is later. If moved earlier, it's fine
        check_for_late_cancellation(current_user, reservation_to_cancel)

    policy_problems, overridable = policy.check_to_save_reservation(
        cancelled_reservation=reservation_to_cancel,
        new_reservation=new_reservation,
        user_creating_reservation=request.user,
        explicit_policy_override=explicit_policy_override,
    )
    if policy_problems:
        reservation_action = "resize" if start_delta is None else "move"
        return render(
            request,
            "calendar/policy_dialog.html",
            {
                "policy_problems": policy_problems,
                "overridable": overridable and (request.user.is_staff or staff_on_tool),
                "reservation_action": reservation_action,
            },
        )
    else:
        # All policy checks passed, so save the reservation.
        new_reservation.save_and_notify()
        reservation_to_cancel.descendant = new_reservation
        reservation_to_cancel.save_and_notify()
        send_tool_free_time_notification(request, reservation_to_cancel, new_reservation)
    return reservation_success(request, new_reservation)


def modify_outage(request, start_delta, end_delta):
    try:
        outage = ScheduledOutage.objects.get(pk=request.POST.get("id"))
    except ScheduledOutage.DoesNotExist:
        return HttpResponseNotFound("The outage that you wish to modify doesn't exist!")
    if not request.user.is_staff and not request.user.is_staff_on_tool(outage.tool):
        return HttpResponseBadRequest("You are not allowed to modify this outage.")
    if start_delta:
        outage.start += start_delta
    if end_delta:
        outage.end += end_delta
    response = policy.check_to_create_outage(outage)
    if response.status_code != HTTPStatus.OK:
        return response
    else:
        # All policy checks passed, so save the reservation.
        outage.save()
    return HttpResponse()


@login_required
@require_POST
def cancel_reservation(request, reservation_id):
    """Cancel a reservation for a user."""
    reservation = get_object_or_404(Reservation, id=reservation_id)

    reason = parse_parameter_string(request.POST, "reason")
    response = cancel_the_reservation(
        reservation=reservation, user_cancelling_reservation=request.user, reason=reason, request=request
    )
    send_tool_free_time_notification(request, reservation)
    if request.device == "desktop":
        return response
    if request.device == "mobile":
        if response.status_code == HTTPStatus.OK:
            return render(
                request, "mobile/cancellation_result.html", {"event_type": "Reservation", "tool": reservation.tool}
            )
        else:
            return render(request, "mobile/error.html", {"message": response.content})


@staff_member_or_tool_staff_required
@require_POST
def cancel_outage(request, outage_id):
    outage = get_object_or_404(ScheduledOutage, id=outage_id)
    if not request.user.is_staff and not request.user.is_staff_on_tool(outage.tool):
        return HttpResponseBadRequest("You are not allowed to cancel this outage.")
    outage.delete()
    if request.device == "desktop":
        return HttpResponse()
    if request.device == "mobile":
        dictionary = {"event_type": "Scheduled outage", "tool": outage.tool, "area": outage.area}
        return render(request, "mobile/cancellation_result.html", dictionary)


@staff_member_or_tool_staff_required
@require_POST
def set_reservation_title(request, reservation_id):
    """Change reservation title for a user."""
    reservation = get_object_or_404(Reservation, id=reservation_id)
    if not request.user.is_staff_on_tool(reservation.tool):
        return HttpResponseBadRequest("You are not allowed to edit this reservation.")
    reservation.title = request.POST.get("title", "")[: reservation._meta.get_field("title").max_length]
    reservation.save_and_notify()
    return HttpResponse()


@login_required
@require_POST
def change_reservation_note(request, reservation_id):
    reservation = get_object_or_404(Reservation, id=reservation_id)
    if (
        not request.user == reservation.user
        and not request.user.is_staff
        and not request.user.is_staff_on_tool(reservation.tool)
    ):
        return HttpResponseBadRequest("You are not allowed to edit this reservation.")
    reservation.note = request.POST.get("note", "")
    reservation.save_and_notify()
    return HttpResponse()


@staff_member_or_tool_staff_required
@require_POST
def change_outage_title(request, outage_id):
    outage = get_object_or_404(ScheduledOutage, id=outage_id)
    if not request.user.is_staff and not request.user.is_staff_on_tool(outage.tool):
        return HttpResponseBadRequest("You are not allowed to edit this outage.")
    outage.title = request.POST.get("title", "")[: outage._meta.get_field("title").max_length]
    outage.save(update_fields=["title"])
    return HttpResponse()


@staff_member_or_tool_staff_required
@require_POST
def change_outage_details(request, outage_id):
    outage = get_object_or_404(ScheduledOutage, id=outage_id)
    if not request.user.is_staff and not request.user.is_staff_on_tool(outage.tool):
        return HttpResponseBadRequest("You are not allowed to edit this outage.")
    outage.details = request.POST.get("details", "")
    outage.save(update_fields=["details"])
    return HttpResponse()


@login_required
@require_POST
def change_reservation_date(request):
    """Change a reservation's start or end date for a user."""
    reservation = get_object_or_404(Reservation, id=request.POST["id"])
    start_delta, end_delta = None, None
    new_start = request.POST.get("new_start", None)
    if new_start:
        try:
            new_start = make_aware(datetime.strptime(new_start, datetime_input_format))
            if new_start.time().minute not in [0, 15, 30, 45]:
                return HttpResponseBadRequest("Reservation time only works with 15 min increments")
        except ValueError:
            return HttpResponseBadRequest("Invalid date format for start date")
        start_delta = new_start - reservation.start
    new_end = request.POST.get("new_end", None)
    if new_end:
        try:
            new_end = make_aware(datetime.strptime(new_end, datetime_input_format))
            if new_end.time().minute not in [0, 15, 30, 45]:
                return HttpResponseBadRequest("Reservation time only works with 15 min increments")
        except ValueError:
            return HttpResponseBadRequest("Invalid date format for end date")
        end_delta = (new_end - reservation.end) if new_end else None
    if start_delta or end_delta:
        return modify_reservation(request, request.user, start_delta, end_delta)
    else:
        return HttpResponseBadRequest("Invalid delta")


@staff_member_or_tool_staff_required
@require_POST
def change_outage_date(request):
    """Change an outage's start or end date."""
    outage = get_object_or_404(ScheduledOutage, id=request.POST["id"])
    if not request.user.is_staff and not request.user.is_staff_on_tool(outage.tool):
        return HttpResponseBadRequest("You are not allowed to edit this outage.")
    start_delta, end_delta = None, None
    new_start = request.POST.get("new_start", None)
    if new_start:
        try:
            new_start = make_aware(datetime.strptime(new_start, datetime_input_format))
            if new_start.time().minute not in [0, 15, 30, 45]:
                return HttpResponseBadRequest("Outage time only works with 15 min increments")
        except ValueError:
            return HttpResponseBadRequest("Invalid date format for start date")
        start_delta = new_start - outage.start
    new_end = request.POST.get("new_end", None)
    if new_end:
        try:
            new_end = make_aware(datetime.strptime(new_end, datetime_input_format))
            if new_end.time().minute not in [0, 15, 30, 45]:
                return HttpResponseBadRequest("Outage time only works with 15 min increments")
        except ValueError:
            return HttpResponseBadRequest("Invalid date format for end date")
        end_delta = (new_end - outage.end) if new_end else None
    if start_delta or end_delta:
        return modify_outage(request, start_delta, end_delta)
    else:
        return HttpResponseBadRequest("Invalid delta")


@login_required
@require_POST
def change_reservation_project(request, reservation_id):
    """Change the reservation project for a user."""
    reservation = get_object_or_404(Reservation, id=reservation_id)
    project = get_object_or_404(Project, id=request.POST["project_id"])
    try:
        policy.check_billing_to_project(project, reservation.user, reservation.reservation_item, reservation)
    except ProjectChargeException as e:
        return HttpResponseBadRequest(e.msg)

    if (
        (request.user.is_staff or request.user.is_staff_on_tool(reservation.tool) or request.user == reservation.user)
        and reservation.has_not_ended()
        and reservation.has_not_started()
        and project in reservation.user.active_projects()
    ):
        reservation.project = project
        reservation.save()
    else:
        # project for reservation was not eligible to be changed
        if not (
            request.user.is_staff or request.user.is_staff_on_tool(reservation.tool) or request.user == reservation.user
        ):
            return HttpResponseForbidden(f"{request.user} is not authorized to change the project for this reservation")
        if not reservation.has_not_ended():
            return HttpResponseBadRequest("Project cannot be changed; reservation has already ended")
        if not reservation.has_not_started():
            return HttpResponseBadRequest("Project cannot be changed; reservation has already started")
        if project not in reservation.user.active_projects():
            return HttpResponseForbidden(f"{project} is not one of {reservation.user}'s active projects")
    return HttpResponse()


@staff_member_or_tool_staff_required
@require_GET
def proxy_reservation(request):
    return render(request, "calendar/proxy_reservation.html", {"users": User.objects.filter(is_active=True)})


@login_required
@require_GET
def get_selected_tool_calendar_info(request, tool_id):
    tool = get_object_or_404(Tool.objects.prefetch_related("comment_set"), pk=tool_id)
    other_problems = tool.problems().count() - 1
    last_problem = tool.problems().latest("creation_time") if other_problems != -1 else None
    return render(
        request,
        "snippets/tool_calendar_info.html",
        {"tool": tool, "other_problems": other_problems, "last_problem": last_problem},
    )


def shorten_reservation(user: User, item: Union[Area, Tool], new_end: datetime = None, force=False):
    try:
        if new_end is None:
            new_end = timezone.now()
        current_reservation_qs = Reservation.objects.filter(
            start__lt=timezone.now(), end__gt=timezone.now(), cancelled=False, missed=False, shortened=False, user=user
        )
        current_reservation = current_reservation_qs.get(**{ReservationItemType.from_item(item).value: item})
        # Staff are exempt from mandatory reservation shortening.
        if (user.is_staff is False and user.is_staff_on_tool(item) is False) or force:
            new_reservation = current_reservation.copy(new_end=new_end)
            new_reservation.save()
            current_reservation.shortened = True
            current_reservation.descendant = new_reservation
            current_reservation.save()
            send_tool_free_time_notification(None, current_reservation, new_reservation, missed_or_shortened=True)
    except Reservation.DoesNotExist:
        pass


def cancel_the_reservation(
    reservation: Reservation, user_cancelling_reservation: User, reason: Optional[str], request=None
):
    # Check policy to cancel reservation contains rules common to cancelling and modifying
    response = policy.check_to_cancel_reservation(user_cancelling_reservation, reservation)

    # The following rules apply only for proper cancellation, not for modification
    # Staff must provide a reason when cancelling a reservation they do not own.
    if reservation.user != user_cancelling_reservation and not reason:
        response = HttpResponseBadRequest("You must provide a reason when cancelling someone else's reservation.")

    policy_problems = []
    policy.check_tool_reservation_requiring_area(policy_problems, user_cancelling_reservation, reservation, None)
    if policy_problems:
        return HttpResponseBadRequest(policy_problems[0])

    if response.status_code == HTTPStatus.OK:
        # All policy checks passed, so cancel the reservation.
        reservation.cancelled = True
        reservation.cancellation_time = timezone.now()
        reservation.cancelled_by = user_cancelling_reservation

        check_for_late_cancellation(user_cancelling_reservation, reservation)

        if reason:
            """don't notify (just save) in this case since we are sending a specific email for the cancellation"""
            reservation.save()
            email_contents = get_media_file_contents("cancellation_email.html")
            if email_contents:
                dictionary = {
                    "staff_member": user_cancelling_reservation,
                    "reservation": reservation,
                    "reason": reason,
                    "template_color": bootstrap_primary_color("info"),
                }
                cancellation_email = render_email_template(email_contents, dictionary, request)
                recipients = reservation.user.get_emails(
                    reservation.user.get_preferences().email_send_reservation_emails
                )
                if reservation.area:
                    recipients.extend(reservation.area.reservation_email_list())
                if reservation.user.get_preferences().attach_cancelled_reservation:
                    event_name = reservation.title or f"{reservation.reservation_item.name} Reservation"
                    attachment = create_ics(
                        reservation.id, event_name, reservation.start, reservation.end, reservation.user, cancelled=True
                    )
                    send_mail(
                        subject="Your reservation was cancelled",
                        content=cancellation_email,
                        from_email=user_cancelling_reservation.email,
                        to=recipients,
                        attachments=[attachment],
                    )
                else:
                    send_mail(
                        subject="Your reservation was cancelled",
                        content=cancellation_email,
                        from_email=user_cancelling_reservation.email,
                        to=recipients,
                    )

        else:
            """here the user cancelled his own reservation so notify him"""
            reservation.save_and_notify()

    return response


# Mark the reservation as missed if it was canceled late by non-staff users
def check_for_late_cancellation(user, reservation):
    tool = reservation.tool
    if tool and (
        not tool.operational or tool.required_resource_is_unavailable() or tool.scheduled_outage_in_progress()
    ):
        # If the tool is down, do not mark as missed
        return

    late_cancellation_threshold = reservation.reservation_item.late_cancellation_reservation_threshold
    if late_cancellation_threshold and not user.is_staff_on_tool(reservation.tool):
        late_deletion = (reservation.start - timezone.now()).total_seconds() < late_cancellation_threshold * 60
        if late_deletion:
            reservation.missed = True


def send_user_created_reservation_notification(reservation: Reservation):
    user = reservation.user
    recipients = (
        user.get_emails(user.get_preferences().email_send_reservation_emails)
        if user.get_preferences().attach_created_reservation
        else []
    )
    if reservation.area:
        recipients.extend(reservation.area.reservation_email_list())
    if recipients:
        subject = f"Reservation for the " + str(reservation.reservation_item)
        message = get_media_file_contents("reservation_created_user_email.html")
        message = render_email_template(message, {"reservation": reservation})
        user_office_email = EmailsCustomization.get("user_office_email_address")
        # We don't need to check for existence of reservation_created_user_email because we are attaching the ics reservation and sending the email regardless (message will be blank)
        if user_office_email:
            event_name = reservation.title or f"{reservation.reservation_item.name} Reservation"
            attachment = create_ics(
                reservation.id,
                event_name,
                reservation.start,
                reservation.end,
                reservation.user,
                description=reservation.note,
            )
            send_mail(
                subject=subject, content=message, from_email=user_office_email, to=recipients, attachments=[attachment]
            )
        else:
            calendar_logger.error(
                "User created reservation notification could not be send because user_office_email_address is not defined"
            )


def send_user_cancelled_reservation_notification(reservation: Reservation):
    user = reservation.user
    recipients = (
        user.get_emails(user.get_preferences().email_send_reservation_emails)
        if user.get_preferences().attach_cancelled_reservation
        else []
    )
    if reservation.area:
        recipients.extend(reservation.area.reservation_email_list())
    if recipients:
        subject = f"Cancelled Reservation for the " + str(reservation.reservation_item)
        message = get_media_file_contents("reservation_cancelled_user_email.html")
        message = render_email_template(message, {"reservation": reservation})
        user_office_email = EmailsCustomization.get("user_office_email_address")
        # We don't need to check for existence of reservation_cancelled_user_email because we are attaching the ics reservation and sending the email regardless (message will be blank)
        if user_office_email:
            event_name = reservation.title or f"{reservation.reservation_item.name} Reservation"
            attachment = create_ics(
                reservation.id, event_name, reservation.start, reservation.end, reservation.user, cancelled=True
            )
            send_mail(
                subject=subject, content=message, from_email=user_office_email, to=recipients, attachments=[attachment]
            )
        else:
            calendar_logger.error(
                "User cancelled reservation notification could not be send because user_office_email_address is not defined"
            )


@login_required
@require_POST
def delete_tool_list(request, tool_list_id):
    user_list = get_object_or_404(UserCalendarToolList, id=tool_list_id)
    if user_list.user == request.user:
        user_list.delete()
    else:
        return HttpResponseBadRequest("You are not authorized to delete this list.")
    return HttpResponse()


@login_required
@require_POST
def save_tool_list(request, tool_list_name):
    user: User = request.user
    tool_list = request.POST.getlist("tools[]")
    if not tool_list:
        return HttpResponseBadRequest("no tool list provided")
    user_tool_list, created = UserCalendarToolList.objects.get_or_create(user=user, name=tool_list_name)
    user_tool_list.tools.set(tool_list)
    return HttpResponse()


@login_required
@require_GET
def load_tool_lists(request):
    user: User = request.user
    user_tool_lists = UserCalendarToolList.objects.filter(user=user)
    return render(request, "calendar/user_tool_lists.html", {"user_tool_lists": user_tool_lists})


@postpone
def send_tool_free_time_notification(
    request,
    cancelled_reservation: Reservation,
    new_reservation: Optional[Reservation] = None,
    missed_or_shortened=False,
):
    tool = cancelled_reservation.tool
    if tool and (cancelled_reservation.start > timezone.now() or missed_or_shortened):
        max_duration = cancelled_reservation.duration().total_seconds() / 60
        freed_time = None
        start_time = None
        days_in_the_future = (cancelled_reservation.start - timezone.now()).total_seconds() / 3600 / 24
        if not new_reservation:
            # this is a cancel action, we only have to take into account the cancelled time
            freed_time = max_duration
            start_time = cancelled_reservation.start
        else:
            # this is a modification (move or resize)
            end_diff = (cancelled_reservation.end - new_reservation.end).total_seconds() / 60
            if cancelled_reservation.start == new_reservation.start and end_diff > 0:
                # reservation was shrunk
                freed_time = end_diff
                start_time = cancelled_reservation.end - timedelta(minutes=end_diff)
            elif cancelled_reservation.start != new_reservation.start:
                # reservation was moved
                freed_time = min(max_duration, abs(end_diff))
                start_time = (
                    (cancelled_reservation.end - timedelta(minutes=freed_time))
                    if end_diff > 0
                    else cancelled_reservation.start
                )
        if freed_time and start_time:
            tool_notifications = UserPreferences.objects.filter(
                tool_freed_time_notifications__in=[tool],
                tool_freed_time_notifications_min_time__lte=freed_time,
                tool_freed_time_notifications_max_future_days__gte=days_in_the_future,
            )
            formatted_start = format_datetime(start_time)
            formatted_time = f"{freed_time:0.0f}"
            link = get_full_url(reverse("calendar"), request)
            user_ids = distinct_qs_value_list(tool_notifications, "user")
            # Special case when shortened, where we notify the user who has the next reservation
            notify_next_res = ToolCustomization.get_bool("tool_freed_time_notify_next_reservation_enabled")
            min_freed_time = ToolCustomization.get_int("tool_freed_time_notify_next_reservation_min_freed_time")
            if notify_next_res and missed_or_shortened and cancelled_reservation.end and freed_time >= min_freed_time:
                # get next reservation user who had a reservation starting within
                hours_within = ToolCustomization.get_int("tool_freed_time_notify_next_reservation_starts_within")
                next_reservations = Reservation.objects.filter(
                    cancelled=False,
                    tool=tool,
                    start__gt=cancelled_reservation.end,
                    start__lte=cancelled_reservation.end + timedelta(hours=hours_within),
                )
                if next_reservations:
                    next_reservation = next_reservations.earliest("start")
                    if next_reservation and next_reservation.user_id not in user_ids:
                        user_ids.add(next_reservation.user_id)
            include_username = ToolCustomization.get_bool("tool_freed_time_notification_include_username")
            for user in User.objects.in_bulk(user_ids).values():
                if user != cancelled_reservation.user:
                    include_username_message = f" by {cancelled_reservation.user.username}" if include_username else ""
                    subject = f"[{tool.name}] {formatted_time} minutes freed starting {formatted_start}"
                    message = f"Dear {user.first_name},<br>\n"
                    message += f"The following time slot has been freed for the {tool.name}{include_username_message}:<br><br>\n\n"
                    message += f"Start: {formatted_start}<br>\n"
                    message += f"End: {format_datetime(start_time + timedelta(minutes=freed_time))}<br>\n"
                    message += f"Duration: {formatted_time} minutes<br><br>\n\n"
                    message += f'Go to the <a href={link} target="_blank">calendar</a> to make a reservation.<br>\n'
                    user.email_user(
                        subject=subject,
                        message=message,
                        from_email=get_email_from_settings(),
                        email_notification=user.get_preferences().email_send_reservation_emails,
                    )
