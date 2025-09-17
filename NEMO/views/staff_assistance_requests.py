from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest
from django.utils import timezone
from django.shortcuts import get_object_or_404, redirect, render
from django.template.defaultfilters import linebreaksbr
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from NEMO.forms import StaffAssistanceRequestForm
from NEMO.models import StaffAssistanceRequest, Notification, RequestMessage, User
from NEMO.utilities import get_email_from_settings, get_full_url
from NEMO.views.customization import UserRequestsCustomization
from NEMO.views.notifications import (
    create_staff_assistance_request_notification,
    create_request_message_notification,
    delete_notification,
    get_notifications,
)


@login_required
@require_GET
def staff_assistance_requests(request):
    if not UserRequestsCustomization.get_bool("staff_assistance_requests_enabled"):
        return HttpResponseBadRequest("Staff assistance requests are not enabled")

    user: User = request.user
    if user.is_staff:
        open_staff_assistance_requests = StaffAssistanceRequest.objects.filter(resolved=False, deleted=False)
        resolved_staff_assistance_requests = StaffAssistanceRequest.objects.filter(resolved=True, deleted=False)
    else:
        open_staff_assistance_requests = StaffAssistanceRequest.objects.filter(user=user, resolved=False, deleted=False)
        resolved_staff_assistance_requests = StaffAssistanceRequest.objects.filter(
            user=user, resolved=True, deleted=False
        )

    dictionary = {
        "open_staff_assistance_requests": open_staff_assistance_requests.order_by("-creation_time"),
        "resolved_staff_assistance_requests": resolved_staff_assistance_requests.order_by("-creation_time"),
        "staff_assistance_requests_description": UserRequestsCustomization.get("staff_assistance_requests_description"),
        "request_notifications": get_notifications(
            request.user, Notification.Types.STAFF_ASSISTANCE_REQUEST, delete=False
        ),
        "reply_notifications": get_notifications(request.user, Notification.Types.STAFF_ASSISTANCE_REQUEST_REPLY),
    }
    return render(request, "requests/staff_assistance_requests/staff_assistance_requests.html", dictionary)


@login_required
@require_POST
def create_staff_assistance_request(request, request_id=None):
    if not UserRequestsCustomization.get_bool("staff_assistance_requests_enabled"):
        return HttpResponseBadRequest("Staff assistance requests are not enabled")

    try:
        staff_assistance_request = StaffAssistanceRequest.objects.get(id=request_id)
    except StaffAssistanceRequest.DoesNotExist:
        staff_assistance_request = None

    if staff_assistance_request:
        if staff_assistance_request.replies.count() > 0:
            return HttpResponseBadRequest("You are not allowed to edit a request that has replies.")
        if staff_assistance_request.user != request.user:
            return HttpResponseBadRequest("You are not allowed to edit a request you didn't create.")

    form = StaffAssistanceRequestForm(request.POST, instance=staff_assistance_request)
    form.fields["user"].required = False
    form.fields["creation_time"].required = False
    if form.is_valid():
        form.instance.user = request.user
        created_staff_assistance_request = form.save()
        send_new_request_emails(
            created_staff_assistance_request,
            get_full_url(
                f"{reverse('user_requests', kwargs={'tab': 'staff_assistance'})}?#request_{created_staff_assistance_request.id}",
                request,
            ),
        )
        create_staff_assistance_request_notification(created_staff_assistance_request)
    return redirect("user_requests", "staff_assistance")


@login_required
@require_POST
def delete_staff_assistance_request(request, request_id):
    if not UserRequestsCustomization.get_bool("staff_assistance_requests_enabled"):
        return HttpResponseBadRequest("Staff assistance requests are not enabled")

    staff_assistance_request = get_object_or_404(StaffAssistanceRequest, id=request_id)

    if staff_assistance_request.replies.count() > 0:
        return HttpResponseBadRequest("You are not allowed to delete a request that has replies.")
    if staff_assistance_request.user != request.user:
        return HttpResponseBadRequest("You are not allowed to delete a request you didn't create.")

    staff_assistance_request.deleted = True
    staff_assistance_request.save(update_fields=["deleted"])
    delete_notification(Notification.Types.STAFF_ASSISTANCE_REQUEST, staff_assistance_request.id)
    return redirect("user_requests", "staff_assistance")


@login_required
@require_POST
def resolve_staff_assistance_request(request, request_id):
    if not UserRequestsCustomization.get_bool("staff_assistance_requests_enabled"):
        return HttpResponseBadRequest("Staff assistance requests are not enabled")

    staff_assistance_request = get_object_or_404(StaffAssistanceRequest, id=request_id)

    if not request.user.is_staff and not staff_assistance_request.user == request.user:
        return HttpResponseBadRequest(
            "You are not allowed to resolve a request if you are not staff or you didn't create it."
        )

    staff_assistance_request.resolved = True
    staff_assistance_request.save(update_fields=["resolved"])
    delete_notification(Notification.Types.STAFF_ASSISTANCE_REQUEST, staff_assistance_request.id)
    return redirect("user_requests", "staff_assistance")


@login_required
@require_POST
def reopen_staff_assistance_request(request, request_id):
    if not UserRequestsCustomization.get_bool("staff_assistance_requests_enabled"):
        return HttpResponseBadRequest("Staff assistance requests are not enabled")

    staff_assistance_request = get_object_or_404(StaffAssistanceRequest, id=request_id)

    if not request.user.is_staff:
        return HttpResponseBadRequest("You are not allowed to reopen a request if you are not staff.")

    staff_assistance_request.resolved = False
    staff_assistance_request.save(update_fields=["resolved"])
    create_staff_assistance_request_notification(staff_assistance_request)
    return redirect("user_requests", "staff_assistance")


@login_required
@require_POST
def staff_assistance_request_reply(request, request_id):
    if not UserRequestsCustomization.get_bool("staff_assistance_requests_enabled"):
        return HttpResponseBadRequest("Staff assistance requests are not enabled")

    staff_assistance_request = get_object_or_404(StaffAssistanceRequest, id=request_id)
    user: User = request.user
    message_content = request.POST["reply_content"]
    expiration = timezone.now() + timedelta(days=30)  # 30 days for adjustment requests replies to expire

    if message_content:
        reply = RequestMessage()
        reply.content_object = staff_assistance_request
        reply.content = message_content
        reply.author = user
        reply.save()
        create_request_message_notification(reply, Notification.Types.STAFF_ASSISTANCE_REQUEST_REPLY, expiration)
        send_reply_emails(
            reply,
            get_full_url(f"{reverse('user_requests', kwargs={'tab': 'staff_assistance'})}?#reply_{reply.id}", request),
        )
    return redirect("user_requests", "staff_assistance")


def send_new_request_emails(staff_assistance_request: StaffAssistanceRequest, request_url):
    all_staff = User.objects.filter(is_active=True, is_staff=True)
    for user in all_staff:
        subject = f"New staff assistance request created by {staff_assistance_request.user.get_name()}"
        message = f"""<br><br>
{linebreaksbr(staff_assistance_request.description)}
<br><br>
Please visit {request_url} to reply"""
        email_notification = user.get_preferences().email_send_staff_assistance_request_replies
        user.email_user(
            subject=subject,
            message=message,
            from_email=get_email_from_settings(),
            email_notification=email_notification,
        )


def send_reply_emails(reply: RequestMessage, reply_url):
    creator: User = reply.content_object.user
    for user in reply.content_object.creator_and_reply_users():
        if user != reply.author:
            creator_display = f"{creator.get_name()}'s" if creator != user else "your"
            creator_display_their = creator_display if creator != reply.author else "their"
            subject = f"New reply on {creator_display} staff assistance request"
            message = f"""{reply.author.get_name()} also replied to {creator_display_their} staff assistance request:
<br><br>
{linebreaksbr(reply.content)}
<br><br>
Please visit {reply_url} to reply"""
            email_notification = user.get_preferences().email_send_staff_assistance_request_replies
            user.email_user(
                subject=subject,
                message=message,
                from_email=get_email_from_settings(),
                email_notification=email_notification,
            )
