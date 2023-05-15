from datetime import timedelta
from typing import List

from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.template.defaultfilters import linebreaksbr
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from NEMO.decorators import accounting_or_user_office_or_manager_required
from NEMO.forms import AdjustmentRequestForm
from NEMO.mixins import BillableItemMixin
from NEMO.models import (
    AdjustmentRequest,
    AreaAccessRecord,
    Notification,
    RequestMessage,
    RequestStatus,
    Reservation,
    StaffCharge,
    UsageEvent,
    User,
)
from NEMO.utilities import (
    BasicDisplayTable,
    EmailCategory,
    bootstrap_primary_color,
    export_format_datetime,
    get_email_from_settings,
    get_full_url,
    quiet_int,
    render_email_template,
    send_mail,
)
from NEMO.views.customization import (
    EmailsCustomization,
    UserRequestsCustomization,
    get_media_file_contents,
)
from NEMO.views.notifications import (
    create_adjustment_request_notification,
    create_request_message_notification,
    delete_notification,
    get_notifications,
)


@login_required
@require_GET
def adjustment_requests(request):
    if not UserRequestsCustomization.get_bool("adjustment_requests_enabled"):
        return HttpResponseBadRequest("Adjustment requests are not enabled")

    user: User = request.user
    max_requests = quiet_int(UserRequestsCustomization.get("adjustment_requests_display_max"), None)
    adj_requests = AdjustmentRequest.objects.filter(deleted=False)
    if not user.is_facility_manager and not user.is_user_office and not user.is_accounting_officer:
        adj_requests = adj_requests.filter(creator=user)
    dictionary = {
        "pending_adjustment_requests": adj_requests.filter(status=RequestStatus.PENDING),
        "approved_adjustment_requests": adj_requests.filter(status=RequestStatus.APPROVED)[:max_requests],
        "denied_adjustment_requests": adj_requests.filter(status=RequestStatus.DENIED)[:max_requests],
        "adjustment_requests_description": UserRequestsCustomization.get("adjustment_requests_description"),
        "request_notifications": get_notifications(
            request.user, Notification.Types.ADJUSTMENT_REQUEST, delete=not user.is_facility_manager
        ),
        "reply_notifications": get_notifications(request.user, Notification.Types.ADJUSTMENT_REQUEST_REPLY),
    }
    return render(request, "requests/adjustment_requests/adjustment_requests.html", dictionary)


@login_required
@require_http_methods(["GET", "POST"])
def create_adjustment_request(request, request_id=None, item_type_id=None, item_id=None):
    if not UserRequestsCustomization.get_bool("adjustment_requests_enabled"):
        return HttpResponseBadRequest("Adjustment requests are not enabled")

    user: User = request.user

    try:
        adjustment_request = AdjustmentRequest.objects.get(id=request_id)
    except AdjustmentRequest.DoesNotExist:
        adjustment_request = AdjustmentRequest()

    try:
        item_type = ContentType.objects.get_for_id(item_type_id)
        adjustment_request.item = item_type.get_object_for_this_type(pk=item_id)
    # Show times if not missed reservation or if missed reservation but customization is set to show times anyway
    except ContentType.DoesNotExist:
        pass

    change_times_allowed = can_change_times(adjustment_request.item)

    # only change the times if we are provided with a charge and it's allowed
    if item_type_id and adjustment_request.item and change_times_allowed:
        adjustment_request.new_start = adjustment_request.item.start
        adjustment_request.new_end = adjustment_request.item.end

    dictionary = {
        "change_times_allowed": change_times_allowed,
        "eligible_items": adjustment_eligible_items(user, adjustment_request.item),
    }

    if request.method == "POST":
        # some extra validation needs to be done here because it depends on the user
        edit = bool(adjustment_request.id)
        errors = []
        if edit:
            if adjustment_request.deleted:
                errors.append("You are not allowed to edit deleted requests.")
            if adjustment_request.status != RequestStatus.PENDING:
                errors.append("Only pending requests can be modified.")
            if adjustment_request.creator != user and not user.is_facility_manager:
                errors.append("You are not allowed to edit a request you didn't create.")

        form = AdjustmentRequestForm(
            request.POST,
            instance=adjustment_request,
            initial={"creator": adjustment_request.creator if edit else user},
        )

        # add errors to the form for better display
        for error in errors:
            form.add_error(None, error)

        if form.is_valid():
            if not edit:
                form.instance.creator = user
            if edit and user.is_facility_manager:
                decision = [state for state in ["approve_request", "deny_request"] if state in request.POST]
                if decision:
                    if next(iter(decision)) == "approve_request":
                        adjustment_request.status = RequestStatus.APPROVED
                    else:
                        adjustment_request.status = RequestStatus.DENIED
                    adjustment_request.reviewer = user

            form.instance.last_updated_by = user
            new_adjustment_request = form.save()
            create_adjustment_request_notification(new_adjustment_request)
            if edit:
                # remove notification for current user and other facility managers
                delete_notification(Notification.Types.ADJUSTMENT_REQUEST, adjustment_request.id, [user])
                if user.is_facility_manager:
                    managers = User.objects.filter(is_active=True, is_facility_manager=True)
                    delete_notification(Notification.Types.ADJUSTMENT_REQUEST, adjustment_request.id, managers)
            send_request_received_email(request, new_adjustment_request, edit)
            return redirect("user_requests", "adjustment")
        else:
            item_type = form.cleaned_data.get("item_type")
            item_id = form.cleaned_data.get("item_id")
            if item_type and item_id:
                dictionary["change_times_allowed"] = can_change_times(item_type.get_object_for_this_type(pk=item_id))
            dictionary["form"] = form
            return render(request, "requests/adjustment_requests/adjustment_request.html", dictionary)
    else:
        form = AdjustmentRequestForm(instance=adjustment_request)
        dictionary["form"] = form
        return render(request, "requests/adjustment_requests/adjustment_request.html", dictionary)


@login_required
@require_POST
def adjustment_request_reply(request, request_id):
    if not UserRequestsCustomization.get_bool("adjustment_requests_enabled"):
        return HttpResponseBadRequest("Adjustment requests are not enabled")

    adjustment_request = get_object_or_404(AdjustmentRequest, id=request_id)
    user: User = request.user
    message_content = request.POST["reply_content"]
    expiration = timezone.now() + timedelta(days=30)  # 30 days for adjustment requests replies to expire

    if adjustment_request.status != RequestStatus.PENDING:
        return HttpResponseBadRequest("Replies are only allowed on PENDING requests")
    elif user != adjustment_request.creator and not user.is_facility_manager:
        return HttpResponseBadRequest("Only the creator and managers can reply to adjustment requests")
    elif message_content:
        reply = RequestMessage()
        reply.content_object = adjustment_request
        reply.content = message_content
        reply.author = user
        reply.save()
        create_request_message_notification(reply, Notification.Types.ADJUSTMENT_REQUEST_REPLY, expiration)
        email_interested_parties(
            reply, get_full_url(f"{reverse('user_requests', kwargs={'tab': 'adjustment'})}?#{reply.id}", request)
        )
    return redirect("user_requests", "adjustment")


@login_required
@require_GET
def delete_adjustment_request(request, request_id):
    if not UserRequestsCustomization.get_bool("adjustment_requests_enabled"):
        return HttpResponseBadRequest("Adjustment requests are not enabled")

    adjustment_request = get_object_or_404(AdjustmentRequest, id=request_id)

    if adjustment_request.creator != request.user:
        return HttpResponseBadRequest("You are not allowed to delete a request you didn't create.")
    if adjustment_request and adjustment_request.status != RequestStatus.PENDING:
        return HttpResponseBadRequest("You are not allowed to delete a request that was already completed.")

    adjustment_request.deleted = True
    adjustment_request.save(update_fields=["deleted"])
    delete_notification(Notification.Types.ADJUSTMENT_REQUEST, adjustment_request.id)
    return redirect("user_requests", "adjustment")


def send_request_received_email(request, adjustment_request: AdjustmentRequest, edit):
    user_office_email = EmailsCustomization.get("user_office_email_address")
    adjustment_request_notification_email = get_media_file_contents("adjustment_request_notification_email.html")
    if user_office_email and adjustment_request_notification_email:
        # cc facility managers
        facility_managers: List[User] = list(User.objects.filter(is_active=True, is_facility_manager=True))
        ccs = [
            email
            for user in facility_managers
            for email in user.get_emails(user.get_preferences().email_send_adjustment_request_updates)
        ]
        status = (
            "approved"
            if adjustment_request.status == RequestStatus.APPROVED
            else "denied"
            if adjustment_request.status == RequestStatus.DENIED
            else "updated"
            if edit
            else "received"
        )
        absolute_url = get_full_url(reverse("user_requests", kwargs={"tab": "adjustment"}), request)
        color_type = "success" if status == "approved" else "danger" if status == "denied" else "info"
        dictionary = {
            "template_color": bootstrap_primary_color(color_type),
            "adjustment_request": adjustment_request,
            "status": status,
            "adjustment_requests_url": absolute_url,
            "manager_note": adjustment_request.manager_note if status == "denied" else None,
            "user_office": False,
        }
        message = render_email_template(adjustment_request_notification_email, dictionary)
        email_notification = adjustment_request.creator.get_preferences().email_send_adjustment_request_updates
        send_mail(
            subject=f"Your adjustment request has been {status}",
            content=message,
            from_email=user_office_email,
            to=adjustment_request.creator.get_emails(email_notification),
            cc=ccs,
            email_category=EmailCategory.ADJUSTMENT_REQUESTS,
        )
        # Send separate email to the user office (with the extra note) when a request is approved
        if adjustment_request.status == RequestStatus.APPROVED:
            dictionary["manager_note"] = adjustment_request.manager_note
            dictionary["user_office"] = True
            message = render_email_template(adjustment_request_notification_email, dictionary)
            send_mail(
                subject=f"{adjustment_request.creator.get_name()}'s adjustment request has been {status}",
                content=message,
                from_email=get_email_from_settings(),
                to=[user_office_email],
                cc=ccs,
                email_category=EmailCategory.ADJUSTMENT_REQUESTS,
            )


def email_interested_parties(reply: RequestMessage, reply_url):
    creator: User = reply.content_object.creator
    for user in reply.content_object.creator_and_reply_users():
        if user != reply.author and (user == creator or user.get_preferences().email_new_adjustment_request_reply):
            creator_display = f"{creator.get_name()}'s" if creator != user else "your"
            creator_display_his = creator_display if creator != reply.author else "his"
            subject = f"New reply on {creator_display} adjustment request"
            message = f"""{reply.author.get_name()} also replied to {creator_display_his} adjustment request:
<br><br>
{linebreaksbr(reply.content)}
<br><br>
Please visit {reply_url} to reply"""
            email_notification = user.get_preferences().email_send_adjustment_request_updates
            user.email_user(
                subject=subject,
                message=message,
                from_email=get_email_from_settings(),
                email_notification=email_notification,
                email_category=EmailCategory.ADJUSTMENT_REQUESTS,
            )


def can_change_times(item):
    can_change_reservation_times = UserRequestsCustomization.get_bool("adjustment_requests_missed_reservation_times")
    return item and (not isinstance(item, Reservation) or can_change_reservation_times)


def adjustment_eligible_items(user: User, current_item=None) -> List[BillableItemMixin]:
    item_number = UserRequestsCustomization.get_int("adjustment_requests_charges_display_number")
    date_limit = UserRequestsCustomization.get_date_limit()
    end_filter = {"end__gte": date_limit} if date_limit else {}
    items: List[BillableItemMixin] = []
    if UserRequestsCustomization.get_bool("adjustment_requests_missed_reservation_enabled"):
        items.extend(
            Reservation.objects.filter(user=user, missed=True).filter(**end_filter).order_by("-end")[:item_number]
        )
    if UserRequestsCustomization.get_bool("adjustment_requests_tool_usage_enabled"):
        items.extend(
            UsageEvent.objects.filter(user=user, operator=user, end__isnull=False)
            .filter(**end_filter)
            .order_by("-end")[:item_number]
        )
    if UserRequestsCustomization.get_bool("adjustment_requests_area_access_enabled"):
        items.extend(
            AreaAccessRecord.objects.filter(customer=user, end__isnull=False, staff_charge__isnull=True)
            .filter(**end_filter)
            .order_by("-end")[:item_number]
        )
    if user.is_staff and UserRequestsCustomization.get_bool("adjustment_requests_staff_staff_charges_enabled"):
        # Add all remote charges for staff to request for adjustment
        items.extend(
            UsageEvent.objects.filter(remote_work=True, operator=user, end__isnull=False)
            .filter(**end_filter)
            .order_by("-end")[:item_number]
        )
        items.extend(
            AreaAccessRecord.objects.filter(end__isnull=False, staff_charge__staff_member=user)
            .filter(**end_filter)
            .order_by("-end")[:item_number]
        )
        items.extend(StaffCharge.objects.filter(end__isnull=False, staff_member=user).filter(**end_filter).order_by("-end")[:item_number])
    if current_item and current_item in items:
        items.remove(current_item)
    # Remove already adjusted charges. filter by id first
    for previously_adjusted in AdjustmentRequest.objects.filter(deleted=False, item_id__in=[item.id for item in items]):
        # Then confirm it's the correct item
        if previously_adjusted.item in items:
            items.remove(previously_adjusted.item)
    items.sort(key=lambda x: (x.get_end(), x.get_start()), reverse=True)
    return items[:item_number]


@accounting_or_user_office_or_manager_required
@require_GET
def csv_export(request):
    return adjustments_csv_export(AdjustmentRequest.objects.filter(deleted=False))


def adjustments_csv_export(request_list: List[AdjustmentRequest]) -> HttpResponse:
    table_result = BasicDisplayTable()
    table_result.add_header(("status", "Status"))
    table_result.add_header(("created_date", "Created date"))
    table_result.add_header(("last_updated", "Last updated"))
    table_result.add_header(("creator", "Creator"))
    table_result.add_header(("item", "Item"))
    table_result.add_header(("new_start", "New start"))
    table_result.add_header(("new_end", "New end"))
    table_result.add_header(("difference", "Difference"))
    table_result.add_header(("reviewer", "Reviewer"))
    for req in request_list:
        req: AdjustmentRequest = req
        table_result.add_row(
            {
                "status": req.get_status_display(),
                "created_date": req.creation_time,
                "last_updated": req.last_updated,
                "creator": req.creator,
                "item": req.item.get_display() if req.item else "",
                "new_start": req.new_start,
                "new_end": req.new_end,
                "difference": req.get_time_difference(),
                "reviewer": req.reviewer,
            }
        )

    filename = f"adjustment_requests_{export_format_datetime()}.csv"
    response = table_result.to_csv()
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
