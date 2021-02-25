from datetime import date
from typing import Optional

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest
from django.shortcuts import render, redirect, get_object_or_404
from django.template.defaultfilters import linebreaksbr
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_GET, require_POST

from NEMO.exceptions import (
	InactiveUserError,
	NoActiveProjectsForUserError,
	PhysicalAccessExpiredUserError,
	NoPhysicalAccessUserError,
)
from NEMO.forms import BuddyRequestForm
from NEMO.models import BuddyRequest, Area, User, BuddyRequestMessage
from NEMO.views.customization import get_customization
from NEMO.views.notifications import (
	create_buddy_request_notification,
	delete_buddy_request_notification,
	get_notifications,
	create_buddy_reply_notification,
)
from NEMO.views.policy import check_policy_to_enter_any_area


@login_required
@require_GET
def buddy_system(request):
	mark_requests_expired()
	buddy_requests = BuddyRequest.objects.filter(expired=False, deleted=False).order_by(
		"start", "end", "-creation_time"
	)
	# extend buddy request to add whether or not the current user can reply
	for buddy_request in buddy_requests:
		buddy_request.user_reply_error = check_user_reply_error(buddy_request, request.user)
	dictionary = {
		"buddy_requests": buddy_requests,
		"areas": Area.objects.filter(buddy_system_allowed=True).count(),
		"buddy_board_disclaimer": get_customization("buddy_board_disclaimer"),
		"request_notifications": get_notifications(request.user, BuddyRequest),
		"reply_notifications": get_notifications(request.user, BuddyRequestMessage),
	}
	return render(request, "buddy_system/buddy_system.html", dictionary)


@login_required
@require_http_methods(["GET", "POST"])
def create_buddy_request(request, request_id=None):
	try:
		buddy_request = BuddyRequest.objects.get(id=request_id)
	except BuddyRequest.DoesNotExist:
		buddy_request = None

	dictionary = {"areas": Area.objects.filter(buddy_system_allowed=True)}

	if buddy_request:
		if buddy_request.replies.count() > 0:
			return HttpResponseBadRequest("You are not allowed to edit a request that has replies.")
		if buddy_request.user != request.user:
			return HttpResponseBadRequest("You are not allowed to edit a request you didn't create.")

	if request.method == "POST":
		form = BuddyRequestForm(request.POST, instance=buddy_request)
		form.fields["user"].required = False
		form.fields["creation_time"].required = False
		if form.is_valid():
			form.instance.user = request.user
			created_buddy_request = form.save()
			create_buddy_request_notification(created_buddy_request)
			return redirect("buddy_system")
		else:
			dictionary["form"] = form
			return render(request, "buddy_system/buddy_request.html", dictionary)
	else:
		form = BuddyRequestForm(instance=buddy_request)
		form.user = request.user
		dictionary["form"] = form
		return render(request, "buddy_system/buddy_request.html", dictionary)


@login_required
@require_GET
def delete_buddy_request(request, request_id):
	buddy_request = get_object_or_404(BuddyRequest, id=request_id)

	if buddy_request.replies.count() > 0:
		return HttpResponseBadRequest("You are not allowed to delete a request that has replies.")
	if buddy_request.user != request.user:
		return HttpResponseBadRequest("You are not allowed to delete a request you didn't create.")

	buddy_request.deleted = True
	buddy_request.save(update_fields=["deleted"])
	delete_buddy_request_notification(buddy_request)
	return redirect("buddy_system")


@login_required
@require_POST
def buddy_request_reply(request, request_id):
	buddy_request = get_object_or_404(BuddyRequest, id=request_id)
	user: User = request.user
	message_content = request.POST["reply_content"]

	error_message = check_user_reply_error(buddy_request, user)
	if error_message:
		return HttpResponseBadRequest(error_message)
	elif message_content:
		reply = BuddyRequestMessage()
		reply.buddy_request = buddy_request
		reply.content = message_content
		reply.author = user
		reply.save()
		create_buddy_reply_notification(reply)
		email_interested_parties(reply, request.build_absolute_uri(f"{reverse('buddy_system')}?#{reply.id}"))
	return redirect("buddy_system")


def email_interested_parties(reply: BuddyRequestMessage, reply_url):
	creator: User = reply.buddy_request.user
	for user in reply.buddy_request.creator_and_reply_users():
		if user != reply.author and (user == creator or user.get_preferences().email_new_buddy_request_reply):
			creator_display = f"{creator.get_name()}'s" if creator != user else "your"
			creator_display_his = creator_display if creator != reply.author else "his"
			subject = f"New reply on {creator_display} buddy request"
			message = f"""{reply.author.get_name()} also replied to {creator_display_his} buddy request:
<br><br>
{linebreaksbr(reply.content)}
<br><br>
Please visit {reply_url} to reply"""
			user.email_user(subject=subject, content=message, from_email=settings.SERVER_EMAIL)


def check_user_reply_error(buddy_request: BuddyRequest, user: User) -> Optional[str]:
	error_message = None
	try:
		check_policy_to_enter_any_area(user)
	except InactiveUserError:
		error_message = "You cannot reply to this request because your account has been deactivated"
	except NoActiveProjectsForUserError:
		error_message = "You cannot reply to this request because you don't have any active projects"
	except PhysicalAccessExpiredUserError:
		error_message = "You cannot reply to this request because your facility access has expired"
	except NoPhysicalAccessUserError:
		error_message = "You cannot reply to this request because you do not have access to any areas"
	else:
		if buddy_request.area not in user.accessible_areas():
			error_message = (
				f"You cannot reply to this request because you do not have access to the {buddy_request.area.name}"
			)
	return error_message


def mark_requests_expired():
	BuddyRequest.objects.filter(expired=False, deleted=False, end__lt=date.today()).update(expired=True)
