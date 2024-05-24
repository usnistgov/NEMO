from datetime import date, datetime, timedelta
from logging import getLogger
from typing import Dict, Iterable, List, Set

from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.http import HttpResponse, HttpResponseNotFound
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_GET

from NEMO.forms import nice_errors
from NEMO.models import (
    Alert,
    Area,
    AreaAccessRecord,
    Closure,
    ClosureTime,
    EmailNotificationType,
    Qualification,
    RecurringConsumableCharge,
    RequestStatus,
    Reservation,
    ReservationItemType,
    ScheduledOutage,
    StaffCharge,
    TemporaryPhysicalAccessRequest,
    Tool,
    ToolWaitList,
    UsageEvent,
    User,
)
from NEMO.typing import QuerySetType
from NEMO.utilities import (
    EmailCategory,
    as_timezone,
    beginning_of_the_day,
    bootstrap_primary_color,
    end_of_the_day,
    format_datetime,
    get_email_from_settings,
    get_full_url,
    is_date_in_datetime_range,
    quiet_int,
    render_email_template,
    send_mail,
)
from NEMO.views.area_access import log_out_user
from NEMO.views.calendar import send_tool_free_time_notification
from NEMO.views.customization import (
    ApplicationCustomization,
    CustomizationBase,
    EmailsCustomization,
    RecurringChargesCustomization,
    ToolCustomization,
    UserCustomization,
    UserRequestsCustomization,
    get_media_file_contents,
)

timed_service_logger = getLogger(__name__)


@login_required
@require_GET
@permission_required("NEMO.trigger_timed_services", raise_exception=True)
def cancel_unused_reservations(request):
    return do_cancel_unused_reservations(request)


def do_cancel_unused_reservations(request=None):
    """
    Missed reservation for tools is when there is no tool activity during the reservation time + missed reservation threshold.
    Any tool usage will count, since we don't want to charge for missed reservation when users swap reservation or somebody else gets to use the tool.

    Missed reservation for areas is when there is no area access login during the reservation time + missed reservation threshold
    """

    # Missed Tool Reservations
    tools = Tool.objects.filter(visible=True, _operational=True, _missed_reservation_threshold__isnull=False)
    missed_reservations: List[Reservation] = []
    for tool in tools:
        # If a tool is in use then there's no need to look for unused reservation time.
        if tool.in_use() or tool.required_resource_is_unavailable() or tool.scheduled_outage_in_progress():
            continue
        # Calculate the timestamp of how long a user can be late for a reservation.
        threshold = timezone.now() - timedelta(minutes=tool.missed_reservation_threshold)
        threshold = datetime.replace(threshold, second=0, microsecond=0)  # Round down to the nearest minute.
        # Find the reservations that began exactly at the threshold.
        reservation = Reservation.objects.filter(
            cancelled=False,
            missed=False,
            shortened=False,
            tool=tool,
            user__is_staff=False,
            start=threshold,
            end__gt=timezone.now(),
        )
        for r in reservation:
            # Staff may abandon reservations.
            if r.user.is_staff:
                continue
            # If there was no tool enable or disable event since the threshold timestamp then we assume the reservation has been missed.
            if not (
                UsageEvent.objects.filter(tool_id__in=tool.get_family_tool_ids(), start__gte=threshold).exists()
                or UsageEvent.objects.filter(tool_id__in=tool.get_family_tool_ids(), end__gte=threshold).exists()
            ):
                # Mark the reservation as missed and notify the user & staff.
                r.missed = True
                r.save()
                missed_reservations.append(r)

    # Missed Area Reservations
    areas = Area.objects.filter(missed_reservation_threshold__isnull=False)
    for area in areas:
        # if area has outage or required resource is unavailable, no need to look
        if area.required_resource_is_unavailable() or area.scheduled_outage_in_progress():
            continue

        # Calculate the timestamp of how long a user can be late for a reservation.
        threshold = timezone.now() - timedelta(minutes=area.missed_reservation_threshold)
        threshold = datetime.replace(threshold, second=0, microsecond=0)  # Round down to the nearest minute.
        # Find the reservations that began exactly at the threshold.
        reservation = Reservation.objects.filter(
            cancelled=False,
            missed=False,
            shortened=False,
            area=area,
            user__is_staff=False,
            start=threshold,
            end__gt=timezone.now(),
        )
        for r in reservation:
            # Staff may abandon reservations.
            if r.user.is_staff:
                continue
            # if the user is not already logged in or if there was no area access starting or ending since the threshold timestamp then we assume the reservation was missed
            if not (
                AreaAccessRecord.objects.filter(area__id=area.id, customer=r.user, staff_charge=None, end=None).exists()
                or AreaAccessRecord.objects.filter(area__id=area.id, customer=r.user, start__gte=threshold).exists()
                or AreaAccessRecord.objects.filter(area__id=area.id, customer=r.user, end__gte=threshold).exists()
            ):
                # Mark the reservation as missed and notify the user & staff.
                r.missed = True
                r.save()
                missed_reservations.append(r)

    for r in missed_reservations:
        send_missed_reservation_notification(r, request)
    # Deal with the missed reservation freed time in a separate loop just in case something raises an exception
    for r in missed_reservations:
        if r.tool:
            # This is a fake reservation to free the time between now and the original end of the reservation
            new_reservation = Reservation()
            new_reservation.start = r.start
            new_reservation.end = timezone.now()
            send_tool_free_time_notification(request, r, new_reservation, missed_or_shortened=True)
    return HttpResponse()


def send_missed_reservation_notification(reservation, request=None):
    message = get_media_file_contents("missed_reservation_email.html")
    user_office_email = EmailsCustomization.get("user_office_email_address")
    abuse_email = EmailsCustomization.get("abuse_email_address")
    if message and user_office_email:
        subject = "Missed reservation for the " + str(reservation.reservation_item)
        message = render_email_template(message, {"reservation": reservation}, request)
        recipients = reservation.user.get_emails(reservation.user.get_preferences().email_send_reservation_emails)
        recipients.append(abuse_email)
        recipients.append(user_office_email)
        send_mail(
            subject=subject,
            content=message,
            from_email=user_office_email,
            to=recipients,
            email_category=EmailCategory.TIMED_SERVICES,
        )
    else:
        timed_service_logger.error(
            "Missed reservation email couldn't be send because missed_reservation_email.html or user_office_email are not defined"
        )


@login_required
@require_GET
@permission_required("NEMO.trigger_timed_services", raise_exception=True)
def create_closure_alerts(request):
    return do_create_closure_alerts()


def do_create_closure_alerts():
    future_times = ClosureTime.objects.filter(closure__alert_days_before__isnull=False, end_time__gt=timezone.now())
    for closure_time in future_times:
        create_alert_for_closure_time(closure_time)
    for closure in Closure.objects.filter(notify_managers_last_occurrence=True):
        closure_time_ending = ClosureTime.objects.filter(closure=closure).latest("end_time")
        if as_timezone(closure_time_ending.end_time).date() == date.today():
            email_last_closure_occurrence(closure_time_ending)
    return HttpResponse()


def create_alert_for_closure_time(closure_time: ClosureTime):
    # Create alerts a week before their debut time (closure start - days before) at the latest
    now = timezone.now()
    next_week = now + timedelta(weeks=1)
    closure = closure_time.closure
    alert_start = closure_time.start_time - timedelta(days=closure.alert_days_before)
    time_ready = alert_start <= next_week
    if time_ready:
        # Check if there is already an alert with the same title ending at the closure end time
        alert_already_exist = Alert.objects.filter(title=closure.name, expiration_time=closure_time.end_time).exists()
        if not alert_already_exist:
            Alert.objects.create(
                title=closure.name,
                contents=closure_time.alert_contents(),
                category="Closure",
                debut_time=alert_start,
                expiration_time=closure_time.end_time,
            )


def email_last_closure_occurrence(closure_time):
    facility_manager_emails = [
        email
        for manager in User.objects.filter(is_active=True, is_facility_manager=True)
        for email in manager.get_emails(EmailNotificationType.BOTH_EMAILS)
    ]
    message = f"""
Dear facility manager,<br>
This email is to inform you that today was the last occurrence for the {closure_time.closure.name} facility closure.
<br><br>Go to NEMO -> Detailed administration -> Closures to add more times if needed.
"""
    send_mail(
        subject=f"Last {closure_time.closure.name} occurrence",
        content=message,
        from_email=get_email_from_settings(),
        to=facility_manager_emails,
        email_category=EmailCategory.SYSTEM,
    )


@login_required
@require_GET
@permission_required("NEMO.trigger_timed_services", raise_exception=True)
def check_and_update_wait_list(request):
    return do_check_and_update_wait_list()


def do_check_and_update_wait_list(now=timezone.now()):
    tools_with_wait_list = (
        Tool.objects.filter(toolwaitlist__expired=False, toolwaitlist__deleted=False)
        .exclude(_operation_mode=Tool.OperationMode.REGULAR)
        .distinct()
    )
    time_to_expiration = quiet_int(ToolCustomization.get("tool_wait_list_spot_expiration"), 1)

    for tool in tools_with_wait_list:
        hybrid_mode = tool.operation_mode == Tool.OperationMode.HYBRID

        # Only check the wait list if the tool is not in use
        # And we are not in the hybrid mode exclusion zone (reservation buffer or active reservation)
        if not tool.in_use() and not in_hybrid_mode_reservation_or_buffer_zone(tool, now):
            top_wait_list_entry = tool.top_wait_list_entry()
            last_turn_available_at = top_wait_list_entry.last_turn_available_at if top_wait_list_entry else None
            turn_available_date = get_wait_list_turn_available_date(tool, top_wait_list_entry, hybrid_mode, now)
            first_check = last_turn_available_at is None

            # Notify the next user in the wait list
            if first_check or turn_available_date > last_turn_available_at:
                top_wait_list_entry.last_turn_available_at = turn_available_date
                top_wait_list_entry.save()
                last_turn_available_at = turn_available_date
                notify_next_user_in_wait_list(top_wait_list_entry, time_to_expiration)

            # Check if spot has expired
            if not first_check and now - last_turn_available_at >= timedelta(minutes=time_to_expiration):
                top_wait_list_entry.expired = True
                top_wait_list_entry.date_exited = now
                top_wait_list_entry.save()

                # Use this if we want to notify next user in line in the same tick
                next_user_entry = tool.top_wait_list_entry()
                if next_user_entry:
                    next_user_entry.last_turn_available_at = now
                    next_user_entry.save()
                    notify_next_user_in_wait_list(top_wait_list_entry, time_to_expiration)

    return HttpResponse()


def in_hybrid_mode_reservation_or_buffer_zone(tool, now=timezone.now()):
    """
    In hybrid mode, the wait list is not checked if there is an upcoming reservation within the next "reservation_buffer" minutes,
    or if we are inside an active reservation slot.
    """
    if tool.operation_mode == Tool.OperationMode.HYBRID:
        reservation_buffer = quiet_int(ToolCustomization.get("tool_wait_list_reservation_buffer"), 1)
        upcoming_reservation_within_buffer_or_active_reservation = Reservation.objects.filter(
            tool=tool,
            cancelled=False,
            missed=False,
            shortened=False,
            start__lte=now + timedelta(minutes=reservation_buffer),
            end__gt=now,
        ).exists()
        return upcoming_reservation_within_buffer_or_active_reservation
    return False


def get_wait_list_turn_available_date(tool, entry, hybrid_mode=False, now=timezone.now()):
    """
    User turn becomes available starting from the latest of one of the following dates:
    - The end of the last usage event
    - The end of the last reservation (hybrid mode only)
        - When a reservation is missed, the reservation end is calculated as the start date + the missed reservation threshold.
    - The time the previous user exited the wait list
    """

    last_usage_event = (
        UsageEvent.objects.filter(tool_id__in=tool.get_family_tool_ids(), end__lte=now).order_by("-end").first()
    )
    last_usage_event_end = last_usage_event.end if last_usage_event else None

    last_reservation_end = None
    if hybrid_mode:
        last_reservation = (
            Reservation.objects.filter(Q(end__lte=now) | Q(missed=True), tool=tool).order_by("-end").first()
        )
        last_reservation_end = get_reservation_end(last_reservation) if last_reservation else None

    previous_wait_list_entry = (
        ToolWaitList.objects.filter(Q(expired=True) | Q(deleted=True), tool=tool, date_entered__lt=entry.date_entered)
        .order_by("-date_exited")
        .first()
    )
    previous_wait_list_entry_exited = previous_wait_list_entry.date_exited if previous_wait_list_entry else None

    return sorted(
        [
            last_usage_event_end,
            last_reservation_end,
            previous_wait_list_entry_exited,
        ],
        key=lambda x: (x is not None, x),
        reverse=True,
    )[0]


def get_reservation_end(reservation):
    if not reservation.missed:
        return reservation.end
    else:
        return reservation.start + timedelta(minutes=reservation.tool.missed_reservation_threshold)


def notify_next_user_in_wait_list(entry, time_to_expiration):
    message = get_media_file_contents("wait_list_notification_email.html")
    if message:
        subject = "Your turn for the " + str(entry.tool)
        message = render_email_template(
            message, {"user": entry.user, "tool": entry.tool, "time_to_expiration": time_to_expiration}
        )
        recipients = entry.user.get_emails(entry.user.get_preferences().email_send_wait_list_notification_emails)
        send_mail(
            subject=subject,
            content=message,
            from_email=get_email_from_settings(),
            to=recipients,
            email_category=EmailCategory.TIMED_SERVICES,
        )
    else:
        timed_service_logger.error(
            "Wait list notification email couldn't be send because wait_list_notification_email.html is not defined"
        )


@login_required
@require_GET
@permission_required("NEMO.trigger_timed_services", raise_exception=True)
def email_out_of_time_reservation_notification(request):
    return send_email_out_of_time_reservation_notification(request)


def send_email_out_of_time_reservation_notification(request=None):
    """
    Out of time reservation notification for areas is when a user is still logged in an area but his reservation expired.
    """
    # Exit early if the out of time reservation email template has not been customized for the organization yet.
    # This feature only sends emails, so if the template is not defined there nothing to do.
    if not get_media_file_contents("out_of_time_reservation_email.html"):
        return HttpResponseNotFound(
            "The out of time reservation email template has not been customized for your organization yet. Please visit the customization page to upload a template, then out of time email notifications can be sent."
        )

    out_of_time_user_area = []

    # Find all logged users
    access_records: List[AreaAccessRecord] = (
        AreaAccessRecord.objects.filter(end=None, staff_charge=None)
        .prefetch_related("customer", "area")
        .only("customer", "area")
    )
    for access_record in access_records:
        # staff and service personnel are exempt from out of time notification
        customer = access_record.customer
        area = access_record.area
        if customer.is_staff or customer.is_service_personnel:
            continue

        if area.requires_reservation:
            # Calculate the timestamp of how late a user can be logged in after a reservation ended.
            threshold = (
                timezone.now()
                if not area.logout_grace_period
                else timezone.now() - timedelta(minutes=area.logout_grace_period)
            )
            threshold = datetime.replace(threshold, second=0, microsecond=0)  # Round down to the nearest minute.
            ending_reservations = Reservation.objects.filter(
                cancelled=False,
                missed=False,
                shortened=False,
                area=area,
                user=customer,
                start__lte=timezone.now(),
                end=threshold,
            )
            # find out if a reservation is starting right at the same time (in case of back to back reservations, in which case customer is good)
            starting_reservations = Reservation.objects.filter(
                cancelled=False, missed=False, shortened=False, area=area, user=customer, start=threshold
            )
            if ending_reservations.exists() and not starting_reservations.exists():
                out_of_time_user_area.append(ending_reservations[0])

    for reservation in out_of_time_user_area:
        send_out_of_time_reservation_notification(reservation, request)

    return HttpResponse()


def send_out_of_time_reservation_notification(reservation: Reservation, request=None):
    message = get_media_file_contents("out_of_time_reservation_email.html")
    user_office_email = EmailsCustomization.get("user_office_email_address")
    if message and user_office_email:
        subject = "Out of time in the " + str(reservation.area.name)
        message = render_email_template(message, {"reservation": reservation}, request)
        recipients = reservation.user.get_emails(
            reservation.user.get_preferences().email_send_reservation_ending_reminders
        )
        recipients.extend(reservation.area.abuse_email_list())
        send_mail(
            subject=subject,
            content=message,
            from_email=user_office_email,
            to=recipients,
            email_category=EmailCategory.TIMED_SERVICES,
        )
    else:
        timed_service_logger.error(
            "Out of time reservation email couldn't be send because out_of_time_reservation_email.html or user_office_email are not defined"
        )


@login_required
@permission_required("NEMO.trigger_timed_services", raise_exception=True)
@require_GET
def email_reservation_ending_reminders(request):
    return send_email_reservation_ending_reminders(request)


def send_email_reservation_ending_reminders(request=None):
    # Exit early if the reservation ending reminder email template has not been customized for the organization yet.
    reservation_ending_reminder_message = get_media_file_contents("reservation_ending_reminder_email.html")
    user_office_email = EmailsCustomization.get("user_office_email_address")
    if not reservation_ending_reminder_message:
        timed_service_logger.error(
            "Reservation ending reminder email couldn't be send because either reservation_ending_reminder_email.html is not defined"
        )
        return HttpResponseNotFound(
            "The reservation ending reminder template has not been customized for your organization yet. Please visit the customization page to upload one, then reservation ending reminder email notifications can be sent."
        )

    # We only send ending reservation reminders to users that are currently logged in
    current_logged_in_user = AreaAccessRecord.objects.filter(end=None, staff_charge=None, customer__is_staff=False)
    valid_reservations = Reservation.objects.filter(cancelled=False, missed=False, shortened=False)
    user_area_reservations = valid_reservations.filter(
        area__isnull=False, user__in=current_logged_in_user.values_list("customer", flat=True)
    )

    # Find all reservations that end 30 or 15 min from now, plus or minus 3 minutes to allow for time skew.
    reminder_times = [30, 15]
    tolerance = 3
    time_filter = Q()
    for reminder_time in reminder_times:
        earliest_end = timezone.now() + timedelta(minutes=reminder_time) - timedelta(minutes=tolerance)
        latest_end = timezone.now() + timedelta(minutes=reminder_time) + timedelta(minutes=tolerance)
        new_filter = Q(end__gt=earliest_end, end__lt=latest_end)
        time_filter = time_filter | new_filter
    ending_reservations = user_area_reservations.filter(time_filter)
    # Email a reminder to each user with a reservation ending soon.
    for reservation in ending_reservations:
        starting_reservation = Reservation.objects.filter(
            cancelled=False,
            missed=False,
            shortened=False,
            area=reservation.area,
            user=reservation.user,
            start=reservation.end,
        )
        if starting_reservation.exists():
            continue
        subject = reservation.reservation_item.name + " reservation ending soon"
        rendered_message = render_email_template(
            reservation_ending_reminder_message, {"reservation": reservation}, request
        )
        email_notification = reservation.user.get_preferences().email_send_reservation_ending_reminders
        reservation.user.email_user(
            subject=subject,
            message=rendered_message,
            from_email=user_office_email,
            email_category=EmailCategory.TIMED_SERVICES,
            email_notification=email_notification,
        )
    return HttpResponse()


@login_required
@permission_required("NEMO.trigger_timed_services", raise_exception=True)
@require_GET
def email_usage_reminders(request):
    projects_to_exclude = request.GET.getlist("projects_to_exclude[]")
    return send_email_usage_reminders(projects_to_exclude, request)


def send_email_usage_reminders(projects_to_exclude=None, request=None):
    if projects_to_exclude is None:
        projects_to_exclude = []
    busy_users = AreaAccessRecord.objects.none()
    if ApplicationCustomization.get_bool("area_in_usage_reminders"):
        busy_users = AreaAccessRecord.objects.filter(end=None, staff_charge=None).exclude(
            project__id__in=projects_to_exclude
        )
    busy_tools = UsageEvent.objects.filter(end=None).exclude(project__id__in=projects_to_exclude)

    # Make lists of all the things a user is logged in to.
    # We don't want to send 3 separate emails if a user is logged into three things.
    # Just send one email for all the things!
    aggregate = {}
    for access_record in busy_users:
        key = access_record.customer_id
        aggregate[key] = {
            "user": access_record.customer,
            "resources_in_use": [access_record.area],
        }
    for usage_event in busy_tools:
        key = usage_event.operator_id
        if key in aggregate:
            aggregate[key]["resources_in_use"].append(usage_event.tool.name)
        else:
            aggregate[key] = {
                "user": usage_event.operator,
                "resources_in_use": [usage_event.tool],
            }

    user_office_email = EmailsCustomization.get("user_office_email_address")

    message = get_media_file_contents("usage_reminder_email.html")
    facility_name = ApplicationCustomization.get("facility_name")
    if message:
        subject = f"{facility_name} usage"
        for value in aggregate.values():
            user: User = value["user"]
            resources_in_use = value["resources_in_use"]
            # for backwards compatibility, add it to the user object (that's how it was defined and used in the template)
            user.resources_in_use = resources_in_use
            rendered_message = render_email_template(
                message, {"user": user, "resources_in_use": resources_in_use}, request
            )
            email_notification = user.get_preferences().email_send_usage_reminders
            user.email_user(
                subject=subject,
                message=rendered_message,
                from_email=user_office_email,
                email_category=EmailCategory.TIMED_SERVICES,
                email_notification=email_notification,
            )

    message = get_media_file_contents("staff_charge_reminder_email.html")
    if message:
        busy_staff = StaffCharge.objects.filter(end=None)
        for staff_charge in busy_staff:
            subject = "Active staff charge since " + format_datetime(staff_charge.start)
            rendered_message = render_email_template(message, {"staff_charge": staff_charge}, request)
            email_notification = staff_charge.staff_member.get_preferences().email_send_usage_reminders
            staff_charge.staff_member.email_user(
                subject=subject,
                message=rendered_message,
                from_email=user_office_email,
                email_category=EmailCategory.TIMED_SERVICES,
                email_notification=email_notification,
            )

    return HttpResponse()


@login_required
@permission_required("NEMO.trigger_timed_services", raise_exception=True)
@require_GET
def email_reservation_reminders(request):
    return send_email_reservation_reminders(request)


def send_email_reservation_reminders(request=None):
    # Exit early if the reservation reminder email template has not been customized for the organization yet.
    reservation_reminder_message = get_media_file_contents("reservation_reminder_email.html")
    reservation_warning_message = get_media_file_contents("reservation_warning_email.html")
    if not reservation_reminder_message or not reservation_warning_message:
        timed_service_logger.error(
            "Reservation reminder email couldn't be send because either reservation_reminder_email.html or reservation_warning_email.html is not defined"
        )
        return HttpResponseNotFound(
            "The reservation reminder and/or warning email templates have not been customized for your organization yet. Please visit the customization page to upload both templates, then reservation reminder email notifications can be sent."
        )

    # Find all reservations that are two hours from now, plus or minus 5 minutes to allow for time skew.
    preparation_time = 120
    tolerance = 5
    earliest_start = timezone.now() + timedelta(minutes=preparation_time) - timedelta(minutes=tolerance)
    latest_start = timezone.now() + timedelta(minutes=preparation_time) + timedelta(minutes=tolerance)
    upcoming_reservations = Reservation.objects.filter(
        cancelled=False, start__gt=earliest_start, start__lt=latest_start
    )
    # Email a reminder to each user with an upcoming reservation.
    for reservation in upcoming_reservations:
        item = reservation.reservation_item
        item_type = reservation.reservation_item_type
        if (
            item_type == ReservationItemType.TOOL
            and item.operational
            and not item.problematic()
            and item.all_resources_available()
            or item_type == ReservationItemType.AREA
            and not item.required_resource_is_unavailable()
        ):
            subject = item.name + " reservation reminder"
            rendered_message = render_email_template(
                reservation_reminder_message,
                {"reservation": reservation, "template_color": bootstrap_primary_color("success")},
                request,
            )
        elif (
            item_type == ReservationItemType.TOOL and not item.operational
        ) or item.required_resource_is_unavailable():
            subject = item.name + " reservation problem"
            rendered_message = render_email_template(
                reservation_warning_message,
                {"reservation": reservation, "template_color": bootstrap_primary_color("danger"), "fatal_error": True},
                request,
            )
        else:
            subject = item.name + " reservation warning"
            rendered_message = render_email_template(
                reservation_warning_message,
                {
                    "reservation": reservation,
                    "template_color": bootstrap_primary_color("warning"),
                    "fatal_error": False,
                },
                request,
            )
        user_office_email = EmailsCustomization.get("user_office_email_address")
        email_notification = reservation.user.get_preferences().email_send_reservation_reminders
        reservation.user.email_user(
            subject=subject,
            message=rendered_message,
            from_email=user_office_email,
            email_category=EmailCategory.TIMED_SERVICES,
            email_notification=email_notification,
        )
    return HttpResponse()


@login_required
@permission_required("NEMO.trigger_timed_services", raise_exception=True)
@require_GET
def email_weekend_access_notification(request):
    return send_email_weekend_access_notification()


def send_email_weekend_access_notification():
    """
    Sends a weekend access email to the addresses set in customization with the template provided.
    The email is sent when the first request (each week) that includes weekend access is approved.
    If no weekend access requests are made by the given time on the cutoff day (if set), a no access email is sent.
    """
    try:
        user_office_email = EmailsCustomization.get("user_office_email_address")
        email_to = UserRequestsCustomization.get("weekend_access_notification_emails")
        access_contents = get_media_file_contents("weekend_access_email.html")
        if user_office_email and email_to and access_contents:
            process_weekend_access_notification(user_office_email, email_to, access_contents)
    except Exception as error:
        timed_service_logger.error(error)
    return HttpResponse()


def process_weekend_access_notification(user_office_email, email_to, access_contents):
    today = datetime.today()
    beginning_of_the_week = beginning_of_the_day(today - timedelta(days=today.weekday()))
    cutoff_day = UserRequestsCustomization.get("weekend_access_notification_cutoff_day")
    cutoff_hour = UserRequestsCustomization.get("weekend_access_notification_cutoff_hour")
    # Set the cutoff in actual datetime format
    cutoff_datetime = None
    if cutoff_hour.isdigit() and cutoff_day and cutoff_day.isdigit():
        cutoff_datetime = (beginning_of_the_week + timedelta(days=int(cutoff_day))).replace(hour=int(cutoff_hour))

    end_of_the_week = beginning_of_the_week + timedelta(weeks=1)
    beginning_of_the_weekend = beginning_of_the_week + timedelta(days=5)

    # Approved access request that include weekend time do overlap with weekend date interval.
    approved_weekend_access_requests = TemporaryPhysicalAccessRequest.objects.filter(
        deleted=False, status=RequestStatus.APPROVED
    )
    approved_weekend_access_requests = approved_weekend_access_requests.exclude(start_time__gte=end_of_the_week)
    approved_weekend_access_requests = approved_weekend_access_requests.exclude(end_time__lte=beginning_of_the_weekend)

    cutoff_time_passed = cutoff_datetime and timezone.now() >= cutoff_datetime
    last_sent = CustomizationBase.get("weekend_access_notification_last_sent")
    last_sent_datetime = parse_datetime(last_sent) if last_sent else None
    if (
        (not last_sent_datetime or last_sent_datetime < beginning_of_the_week)
        and access_contents
        and approved_weekend_access_requests.exists()
        and not cutoff_time_passed
    ):
        send_weekend_email_access(True, user_office_email, email_to, access_contents, beginning_of_the_week)
        CustomizationBase.set("weekend_access_notification_last_sent", str(timezone.now()))
    if access_contents and cutoff_datetime and not approved_weekend_access_requests.exists():
        is_cutoff = today.weekday() == int(cutoff_day) and cutoff_datetime.hour == timezone.localtime().hour
        if is_cutoff:
            send_weekend_email_access(False, user_office_email, email_to, access_contents, beginning_of_the_week)


def send_weekend_email_access(access, user_office_email, email_to, contents, beginning_of_the_week):
    facility_name = ApplicationCustomization.get("facility_name")
    recipients = tuple([e for e in email_to.split(",") if e])
    ccs = [
        email
        for manager in User.objects.filter(is_active=True, is_facility_manager=True)
        for email in manager.get_emails(manager.get_preferences().email_send_access_request_updates)
    ]
    ccs.append(user_office_email)

    sat = format_datetime(beginning_of_the_week + timedelta(days=5), "SHORT_DATE_FORMAT", as_current_timezone=False)
    sun = format_datetime(beginning_of_the_week + timedelta(days=6), "SHORT_DATE_FORMAT", as_current_timezone=False)

    subject = f"{'NO w' if not access else 'W'}eekend access for the {facility_name} {sat} - {sun}"
    message = render_email_template(contents, {"weekend_access": access})
    send_mail(
        subject=subject,
        content=message,
        from_email=user_office_email,
        to=recipients,
        cc=ccs,
        email_category=EmailCategory.ACCESS_REQUESTS,
    )


@login_required
@require_GET
@permission_required("NEMO.trigger_timed_services", raise_exception=True)
def email_user_access_expiration_reminders(request):
    return send_email_user_access_expiration_reminders(request)


def send_email_user_access_expiration_reminders(request=None):
    facility_name = ApplicationCustomization.get("facility_name")
    user_office_email = EmailsCustomization.get("user_office_email_address")
    access_expiration_reminder_days = UserCustomization.get("user_access_expiration_reminder_days")
    template = get_media_file_contents("user_access_expiration_reminder_email.html")
    if user_office_email and template and access_expiration_reminder_days:
        user_expiration_reminder_cc = UserCustomization.get("user_access_expiration_reminder_cc")
        ccs = [e for e in user_expiration_reminder_cc.split(",") if e]
        for remaining_days in [int(days) for days in access_expiration_reminder_days.split(",")]:
            expiration_date = date.today() + timedelta(days=remaining_days)
            for user in User.objects.filter(is_active=True, access_expiration=expiration_date):
                subject = f"Your {facility_name} access expires in {remaining_days} days ({format_datetime(user.access_expiration)})"
                message = render_email_template(template, {"user": user, "remaining_days": remaining_days}, request)
                email_notification = user.get_preferences().email_send_access_expiration_emails
                user.email_user(
                    subject=subject,
                    message=message,
                    from_email=user_office_email,
                    cc=ccs,
                    email_notification=email_notification,
                )
    return HttpResponse()


@login_required
@require_GET
@permission_required("NEMO.trigger_timed_services", raise_exception=True)
def manage_tool_qualifications(request):
    return do_manage_tool_qualifications(request)


def do_manage_tool_qualifications(request=None):
    user_office_email = EmailsCustomization.get("user_office_email_address")
    qualification_reminder_days = ToolCustomization.get("tool_qualification_reminder_days")
    qualification_expiration_days = ToolCustomization.get("tool_qualification_expiration_days")
    qualification_expiration_never_used = ToolCustomization.get("tool_qualification_expiration_never_used_days")
    template = get_media_file_contents("tool_qualification_expiration_email.html")
    if user_office_email and template:
        if qualification_expiration_days or qualification_expiration_never_used:
            qualification_expiration_days = quiet_int(qualification_expiration_days, None)
            qualification_expiration_never_used = quiet_int(qualification_expiration_never_used, None)
            for qualification in Qualification.objects.filter(
                user__is_active=True, user__is_staff=False, tool___qualifications_never_expire=False
            ).prefetch_related("tool", "user"):
                user = qualification.user
                tool = qualification.tool
                last_tool_use = None
                try:
                    # Last tool use cannot be before the last time they qualified
                    last_tool_use = max(
                        as_timezone(UsageEvent.objects.filter(user=user, tool=tool).latest("start").start).date(),
                        qualification.qualified_on,
                    )
                    expiration_date: date = (
                        last_tool_use + timedelta(days=qualification_expiration_days)
                        if qualification_expiration_days
                        else None
                    )
                except UsageEvent.DoesNotExist:
                    # User never used the tool, use the qualification date
                    expiration_date: date = (
                        qualification.qualified_on + timedelta(days=qualification_expiration_never_used)
                        if qualification_expiration_never_used
                        else None
                    )
                if expiration_date:
                    if expiration_date <= date.today():
                        qualification.delete()
                        send_tool_qualification_expiring_email(
                            qualification, last_tool_use, expiration_date, request=request
                        )
                    if qualification_reminder_days:
                        for remaining_days in [int(days) for days in qualification_reminder_days.split(",")]:
                            if expiration_date - timedelta(days=remaining_days) == date.today():
                                send_tool_qualification_expiring_email(
                                    qualification, last_tool_use, expiration_date, remaining_days, request=request
                                )
    return HttpResponse()


def send_tool_qualification_expiring_email(
    qualification: Qualification, last_tool_use: date, expiration_date: date, remaining_days: int = None, request=None
):
    user_office_email = EmailsCustomization.get("user_office_email_address")
    template = get_media_file_contents("tool_qualification_expiration_email.html")
    # Add extra cc emails
    tool_qualification_cc = ToolCustomization.get("tool_qualification_cc")
    ccs = [e for e in tool_qualification_cc.split(",") if e]
    if remaining_days:
        subject_expiration = f" expires in {remaining_days} days!"
    else:
        subject_expiration = " has expired"
    subject = f"Your {qualification.tool.name} qualification {subject_expiration}"
    dictionary = {
        "user": qualification.user,
        "tool": qualification.tool,
        "last_tool_use": last_tool_use,
        "expiration_date": expiration_date,
        "qualification_date": qualification.qualified_on,
        "remaining_days": remaining_days,
    }
    message = render_email_template(template, dictionary, request)
    email_notification = qualification.user.get_preferences().email_send_tool_qualification_expiration_emails
    qualification.user.email_user(
        subject=subject, message=message, from_email=user_office_email, cc=ccs, email_notification=email_notification
    )


@login_required
@require_GET
@permission_required("NEMO.trigger_timed_services", raise_exception=True)
def manage_recurring_charges(request):
    return do_manage_recurring_charges(request)


def do_manage_recurring_charges(request=None):
    # Dictionary of user ids and list of recurring charges they need to be reminded of
    user_reminders = {}
    for recurring_charge in RecurringConsumableCharge.objects.filter(customer__isnull=False):
        today = beginning_of_the_day(datetime.now(), in_local_timezone=False)
        next_match_including_today = recurring_charge.next_charge(inc=True)
        if not next_match_including_today:
            continue
        if next_match_including_today == today or next_match_including_today.date() == today.date():
            try:
                recurring_charge.charge()
            except ValidationError as e:
                url = get_full_url(reverse("edit_recurring_charge", args=[recurring_charge.id]), request)
                recurring_charge_name = RecurringChargesCustomization.get("recurring_charges_name")
                user_office_email = EmailsCustomization.get("user_office_email_address")
                content = f'The item "{recurring_charge.name}" <b>could not be charged</b> for the following reason(s):'
                content += f"{nice_errors(e).as_ul()}"
                content += f'You can fix the issue by going to the <a href="{url}">{recurring_charge.name}</a> page.'
                send_mail(
                    subject=f"Error processing {recurring_charge_name.lower()}",
                    content=content,
                    from_email=None,
                    to=[user_office_email],
                )
            except Exception:
                timed_service_logger.exception("Error trying to charge for %s", recurring_charge.name)
        customer: User = recurring_charge.customer
        next_charge = recurring_charge.next_charge()
        if customer.get_preferences().get_recurring_charges_days():
            reminder_days = (next_charge - today).days
            if reminder_days in customer.get_preferences().get_recurring_charges_days():
                key = customer.id
                if key in user_reminders:
                    user_reminders[key]["charges"].append(recurring_charge)
                else:
                    user_reminders[key] = {
                        "user": customer,
                        "reminder_days": reminder_days,
                        "charges": [recurring_charge],
                    }
    send_recurring_charge_reminders(request, user_reminders.values())
    return HttpResponse()


def send_recurring_charge_reminders(request, reminders: Iterable[Dict]):
    message = get_media_file_contents("recurring_charges_reminder_email.html")
    user_office_email = EmailsCustomization.get("user_office_email_address")
    recurring_charges_name = RecurringChargesCustomization.get("recurring_charges_name")
    if message and user_office_email:
        for user_reminders in reminders:
            subject = f"{recurring_charges_name} will be charged in {user_reminders['reminder_days']} day(s)"
            user_instance: User = user_reminders["user"]
            rendered_message = render_email_template(message, user_reminders, request)
            email_notification = user_instance.get_preferences().email_send_recurring_charges_reminder_emails
            user_instance.email_user(
                subject=subject,
                message=rendered_message,
                from_email=user_office_email,
                email_category=EmailCategory.TIMED_SERVICES,
                email_notification=email_notification,
            )


@login_required
@require_GET
@permission_required("NEMO.trigger_timed_services", raise_exception=True)
def auto_logout_users(request):
    return do_auto_logout_users()


def do_auto_logout_users():
    current_logged_in_user_to_logout: QuerySetType[AreaAccessRecord] = AreaAccessRecord.objects.filter(
        area__auto_logout_time__isnull=False, end__isnull=True, staff_charge__isnull=True
    ).prefetch_related("customer", "area")
    for record in current_logged_in_user_to_logout:
        timeout = timedelta(minutes=record.area.auto_logout_time)
        if record.start + timeout <= timezone.now():
            # Using regular logout function for consistency
            log_out_user(record.customer)
            # Now adjust the time, so it's "auto_logout_time" minutes long max
            record.end = record.start + timeout
            record.save(update_fields=["end"])
    return HttpResponse()


@login_required
@require_GET
@permission_required("NEMO.trigger_timed_services", raise_exception=True)
def email_scheduled_outage_reminders(request):
    return send_email_scheduled_outage_reminders(request)


def send_email_scheduled_outage_reminders(request=None) -> HttpResponse:
    # Exit early if the template email is not defined
    message = get_media_file_contents("scheduled_outage_reminder_email.html")
    if not message:
        timed_service_logger.error(
            "Scheduled outage reminder email couldn't be send because scheduled_outage_reminder_email.html is not defined"
        )
        return HttpResponseNotFound(
            "The scheduled outage reminder template has not been customized for your organization yet. Please visit the customization page to upload one, then scheduled outage reminder email notifications can be sent."
        )
    future_outages: QuerySetType[ScheduledOutage] = ScheduledOutage.objects.filter(start__gte=timezone.now())
    outages_to_send_reminders_for: Set[ScheduledOutage] = set()
    for future_outage in future_outages:
        # Skip if we have no email addresses to send it to
        if future_outage.reminder_emails:
            for remaining_days in future_outage.get_reminder_days():
                outage_date = date.today() + timedelta(days=remaining_days)
                # Use the whole day of the start of the outage to check
                start, end = beginning_of_the_day(future_outage.start), end_of_the_day(future_outage.start)
                if is_date_in_datetime_range(outage_date, start, end):
                    outages_to_send_reminders_for.add(future_outage)
    for outage in outages_to_send_reminders_for:
        subject = f"{outage.title} reminder"
        rendered_message = render_email_template(message, {"outage": outage}, request)
        send_mail(
            subject=subject,
            content=rendered_message,
            from_email=get_email_from_settings(),
            to=outage.reminder_emails,
            email_category=EmailCategory.TIMED_SERVICES,
        )
    return HttpResponse()


@login_required
@require_GET
@permission_required("NEMO.trigger_timed_services", raise_exception=True)
def deactivate_access_expired_users(request):
    return do_deactivate_access_expired_users()


def do_deactivate_access_expired_users():
    buffer_days = UserCustomization.get_int("user_access_expiration_buffer_days", 0)
    user_types = UserCustomization.get_list_int("user_access_expiration_types")
    user_no_type = UserCustomization.get_bool("user_access_expiration_no_type")
    filter_type = Q()
    filter_type |= Q(type__isnull=user_no_type)
    if user_no_type:
        filter_type |= Q(type__in=user_types)
    else:
        filter_type &= Q(type__in=user_types)
    users_about_to_expire = User.objects.filter(
        is_active=True, access_expiration__lte=date.today() + timedelta(days=buffer_days)
    ).filter(filter_type)
    for user in users_about_to_expire:
        user.is_active = False
        user.save(update_fields=["is_active"])
    return HttpResponse()
