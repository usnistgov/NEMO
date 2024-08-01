from datetime import timedelta
from typing import List, Set

from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.db.models import F, Q
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
    Area,
    AreaAccessRecord,
    ConsumableWithdraw,
    Notification,
    RequestMessage,
    RequestStatus,
    Reservation,
    StaffCharge,
    Tool,
    UsageEvent,
    User,
)
from NEMO.utilities import (
    BasicDisplayTable,
    EmailCategory,
    bootstrap_primary_color,
    export_format_datetime,
    get_full_url,
    quiet_int,
    render_email_template,
    send_mail,
)
from NEMO.views.customization import EmailsCustomization, UserRequestsCustomization, get_media_file_contents
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
    my_requests = adj_requests.filter(creator=user)

    user_is_reviewer = is_user_a_reviewer(user)
    user_is_staff = user.is_facility_manager or user.is_user_office or user.is_accounting_officer
    if not user_is_reviewer and not user_is_staff:
        # only show own requests
        adj_requests = my_requests
    elif user_is_reviewer:
        # show all requests the user can review, exclude the rest
        exclude = []
        for adj in adj_requests:
            if user != adj.creator and user not in adj.reviewers():
                exclude.append(adj.pk)
        adj_requests = adj_requests.exclude(pk__in=exclude)

    dictionary = {
        "pending_adjustment_requests": adj_requests.filter(status=RequestStatus.PENDING),
        "approved_adjustment_requests": adj_requests.filter(status=RequestStatus.APPROVED)[:max_requests],
        "denied_adjustment_requests": adj_requests.filter(status=RequestStatus.DENIED)[:max_requests],
        "adjustment_requests_description": UserRequestsCustomization.get("adjustment_requests_description"),
        "request_notifications": get_notifications(request.user, Notification.Types.ADJUSTMENT_REQUEST, delete=False),
        "reply_notifications": get_notifications(request.user, Notification.Types.ADJUSTMENT_REQUEST_REPLY),
        "user_is_reviewer": user_is_reviewer,
    }

    # Delete notifications for seen requests
    Notification.objects.filter(
        user=request.user, notification_type=Notification.Types.ADJUSTMENT_REQUEST, object_id__in=my_requests
    ).delete()
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
    except ContentType.DoesNotExist:
        pass

    # Show times if not missed reservation or if missed reservation but customization is set to show times anyway
    change_times_allowed = can_change_times(adjustment_request.item)
    # Show quantity field if we have a consumable
    change_quantity_allowed = isinstance(adjustment_request.item, ConsumableWithdraw)

    # only change the times if we are provided with a charge and it's allowed
    if item_type_id and adjustment_request.item and change_times_allowed:
        adjustment_request.new_start = adjustment_request.item.start
        adjustment_request.new_end = adjustment_request.item.end
    if item_type_id and adjustment_request.item and change_quantity_allowed:
        adjustment_request.new_quantity = adjustment_request.item.quantity

    dictionary = {
        "change_times_allowed": change_times_allowed,
        "change_quantity_allowed": change_quantity_allowed,
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
            if adjustment_request.creator != user and user not in adjustment_request.reviewers():
                errors.append("You are not allowed to edit this request.")

        form = AdjustmentRequestForm(
            request.POST,
            instance=adjustment_request,
            initial={"creator": adjustment_request.creator if edit else user},
        )

        # add errors to the form for better display
        for error in errors:
            form.add_error(None, error)

        if form.is_valid():
            adjust_charge = False
            if not edit:
                form.instance.creator = user
            if edit and user in adjustment_request.reviewers():
                decision = [
                    state
                    for state in ["approve_request", "approve_apply_request", "deny_request"]
                    if state in request.POST
                ]
                if decision:
                    actual_decision = next(iter(decision))
                    if actual_decision.startswith("approve_"):
                        adjustment_request.status = RequestStatus.APPROVED
                        if actual_decision == "approve_apply_request" and UserRequestsCustomization.get_bool(
                            "adjustment_requests_apply_button"
                        ):
                            adjust_charge = True
                    else:
                        adjustment_request.status = RequestStatus.DENIED
                    adjustment_request.reviewer = user

            form.instance.last_updated_by = user
            new_adjustment_request = form.save()

            # We only apply it here in case something goes wrong before when saving it
            if adjust_charge:
                new_adjustment_request.apply_adjustment(user)

            reviewers: Set[User] = set(list(adjustment_request.reviewers()))

            create_adjustment_request_notification(new_adjustment_request)
            if edit:
                # remove notification for current user and other reviewers
                delete_notification(Notification.Types.ADJUSTMENT_REQUEST, adjustment_request.id, [user])
                if user in reviewers:
                    delete_notification(Notification.Types.ADJUSTMENT_REQUEST, adjustment_request.id, reviewers)
            send_request_received_email(request, new_adjustment_request, edit, reviewers)
            return redirect("user_requests", "adjustment")
        else:
            item_type = form.cleaned_data.get("item_type")
            item_id = form.cleaned_data.get("item_id")
            if item_type and item_id:
                dictionary["change_times_allowed"] = can_change_times(item_type.get_object_for_this_type(pk=item_id))
                dictionary["change_quantity_allowed"] = isinstance(
                    item_type.get_object_for_this_type(pk=item_id), ConsumableWithdraw
                )
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
    elif user != adjustment_request.creator and user not in adjustment_request.reviewers():
        return HttpResponseBadRequest("Only the creator and reviewers can reply to adjustment requests")
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
    if adjustment_request.status != RequestStatus.PENDING:
        return HttpResponseBadRequest("You are not allowed to delete a request that was already completed.")

    adjustment_request.deleted = True
    adjustment_request.save(update_fields=["deleted"])
    delete_notification(Notification.Types.ADJUSTMENT_REQUEST, adjustment_request.id)
    return redirect("user_requests", "adjustment")


@login_required
@require_GET
def mark_adjustment_as_applied(request, request_id):
    user: User = request.user
    if not UserRequestsCustomization.get_bool("adjustment_requests_enabled"):
        return HttpResponseBadRequest("Adjustment requests are not enabled")

    adjustment_request = get_object_or_404(AdjustmentRequest, id=request_id)

    if not user.is_user_office and user not in adjustment_request.reviewers():
        return HttpResponseBadRequest("You are not allowed to mark an adjustment as applied unless you are a reviewer.")
    if adjustment_request.status != RequestStatus.APPROVED:
        return HttpResponseBadRequest(
            "You cannot mark a adjustment as applied unless the request has been approved first"
        )

    adjustment_request.applied = True
    adjustment_request.applied_by = request.user
    adjustment_request.save(update_fields=["applied", "applied_by"])
    return HttpResponse()


@login_required
@require_GET
def apply_adjustment(request, request_id):
    if not UserRequestsCustomization.get_bool("adjustment_requests_enabled"):
        return HttpResponseBadRequest("Adjustment requests are not enabled")
    if not UserRequestsCustomization.get_bool("adjustment_requests_apply_button"):
        return HttpResponseBadRequest("Applying adjustments is not allowed")

    adjustment_request = get_object_or_404(AdjustmentRequest, id=request_id)

    if request.user not in adjustment_request.reviewers():
        return HttpResponseBadRequest("You are not allowed to adjust the charge unless you are a reviewer.")
    if adjustment_request.status != RequestStatus.APPROVED:
        return HttpResponseBadRequest("You cannot apply a adjustment unless the request has been approved first")

    adjustment_request.apply_adjustment(request.user)
    return HttpResponse()


def send_request_received_email(request, adjustment_request: AdjustmentRequest, edit, reviewers: Set[User]):
    user_office_email = EmailsCustomization.get("user_office_email_address")
    adjustment_request_notification_email = get_media_file_contents("adjustment_request_notification_email.html")
    if user_office_email and adjustment_request_notification_email:
        # reviewers
        reviewer_emails = [
            email
            for user in reviewers
            for email in user.get_emails(user.get_preferences().email_send_adjustment_request_updates)
        ]
        status = (
            "approved"
            if adjustment_request.status == RequestStatus.APPROVED
            else "denied" if adjustment_request.status == RequestStatus.DENIED else "updated" if edit else "received"
        )
        absolute_url = get_full_url(reverse("user_requests", kwargs={"tab": "adjustment"}), request)
        color_type = "success" if status == "approved" else "danger" if status == "denied" else "info"
        dictionary = {
            "template_color": bootstrap_primary_color(color_type),
            "adjustment_request": adjustment_request,
            "status": status,
            "adjustment_request_url": absolute_url,
            "manager_note": adjustment_request.manager_note if status == "denied" else None,
            "user_office": False,
        }
        message = render_email_template(adjustment_request_notification_email, dictionary)
        creator_notification = adjustment_request.creator.get_preferences().email_send_adjustment_request_updates
        if status in ["received", "updated"]:
            send_mail(
                subject=f"Adjustment request {status}",
                content=message,
                from_email=adjustment_request.creator.email,
                to=reviewer_emails,
                cc=adjustment_request.creator.get_emails(creator_notification),
                email_category=EmailCategory.ADJUSTMENT_REQUESTS,
            )
        else:
            send_mail(
                subject=f"Your adjustment request has been {status}",
                content=message,
                from_email=adjustment_request.reviewer.email,
                to=adjustment_request.creator.get_emails(creator_notification),
                cc=reviewer_emails,
                email_category=EmailCategory.ADJUSTMENT_REQUESTS,
            )

        # Send separate email to the user office (with the extra note) when a request is approved
        # Unless it's also been applied in which case there is nothing to do so no need to notify them
        if not adjustment_request.applied and adjustment_request.status == RequestStatus.APPROVED:
            dictionary["manager_note"] = adjustment_request.manager_note
            dictionary["user_office"] = True
            message = render_email_template(adjustment_request_notification_email, dictionary)
            send_mail(
                subject=f"{adjustment_request.creator.get_name()}'s adjustment request has been {status}",
                content=message,
                from_email=adjustment_request.reviewer.email,
                to=[user_office_email],
                cc=reviewer_emails,
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
                from_email=reply.author.email,
                email_notification=email_notification,
                email_category=EmailCategory.ADJUSTMENT_REQUESTS,
            )


def can_change_times(item):
    can_change_reservation_times = UserRequestsCustomization.get_bool("adjustment_requests_missed_reservation_times")
    return (
        item
        and not isinstance(item, ConsumableWithdraw)
        and (not isinstance(item, Reservation) or can_change_reservation_times)
    )


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
    if UserRequestsCustomization.get_bool("adjustment_requests_consumable_withdrawal_enabled"):
        date_filter = {"date__gte": date_limit} if date_limit else {}
        consumable_withdrawals = (
            ConsumableWithdraw.objects.filter(customer=user).filter(**date_filter).order_by("-date")
        )
        self_checkout = UserRequestsCustomization.get_bool("adjustment_requests_consumable_withdrawal_self_checkout")
        staff_checkout = UserRequestsCustomization.get_bool("adjustment_requests_consumable_withdrawal_staff_checkout")
        usage_event = UserRequestsCustomization.get_bool("adjustment_requests_consumable_withdrawal_usage_event")
        type_filter = Q()
        if not self_checkout:
            type_filter = type_filter & ~Q(
                consumable__allow_self_checkout=True, merchant=F("customer"), usage_event__isnull=True
            )
        if not staff_checkout:
            type_filter = type_filter & (
                Q(usage_event__isnull=False) | Q(merchant__is_staff=False) | Q(merchant=F("customer"))
            )
        if not usage_event:
            type_filter = type_filter & ~Q(usage_event__isnull=False)
        consumable_withdrawals = consumable_withdrawals.filter(type_filter)
        items.extend(consumable_withdrawals[:item_number])
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
        items.extend(
            StaffCharge.objects.filter(end__isnull=False, staff_member=user)
            .filter(**end_filter)
            .order_by("-end")[:item_number]
        )
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
    table_result.add_header(("applied", "Applied"))
    table_result.add_header(("applied_by", "Applied by"))
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
                "new_quantity": req.new_quantity,
                "difference": req.get_time_difference() or req.get_quantity_difference(),
                "reviewer": req.reviewer,
                "applied": req.applied,
                "applied_by": req.applied_by,
            }
        )

    filename = f"adjustment_requests_{export_format_datetime()}.csv"
    response = table_result.to_csv()
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def is_user_a_reviewer(user: User) -> bool:
    is_reviewer_on_any_tool = Tool.objects.filter(_adjustment_request_reviewers__in=[user]).exists()
    is_reviewer_on_any_area = Area.objects.filter(adjustment_request_reviewers__in=[user]).exists()
    return user.is_facility_manager or is_reviewer_on_any_tool or is_reviewer_on_any_area
