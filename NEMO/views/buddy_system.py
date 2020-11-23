from datetime import datetime
from typing import Optional

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_http_methods, require_GET, require_POST

from NEMO.admin import BuddyRequestForm
from NEMO.exceptions import InactiveUserError, NoActiveProjectsForUserError, PhysicalAccessExpiredUserError, NoPhysicalAccessUserError
from NEMO.models import BuddyRequest, Area, User, BuddyRequestMessage
from NEMO.utilities import beginning_of_the_day
from NEMO.views.customization import get_customization
from NEMO.views.policy import check_policy_to_enter_any_area


@login_required
@require_GET
def buddy_system(request):
	mark_requests_expired()
	buddy_requests = BuddyRequest.objects.filter(expired=False, deleted=False).order_by('start')
	# extend buddy request to add whether or not the current user can reply
	for buddy_request in buddy_requests:
		buddy_request.user_reply_error = check_user_reply_error(buddy_request, request.user)
	dictionary = {
		'buddy_requests': buddy_requests,
		'areas': Area.objects.filter(requires_buddy_after_hours=True).count(),
		'buddy_board_disclaimer': get_customization('buddy_board_disclaimer')
	}
	return render(request, 'buddy_system/buddy_system.html', dictionary)


@login_required
@require_http_methods(['GET', 'POST'])
def create_buddy_request(request, request_id=None):
	try:
		buddy_request = BuddyRequest.objects.get(id=request_id)
	except BuddyRequest.DoesNotExist:
		buddy_request = None

	dictionary = {
		'areas': Area.objects.filter(requires_buddy_after_hours=True),
	}

	if buddy_request:
		if buddy_request.replies.count() > 0:
			return HttpResponseBadRequest("You are not allowed to edit a request that has replies.")
		if buddy_request.user != request.user:
			return HttpResponseBadRequest("You are not allowed to edit a request you didn't create.")

	if request.method == 'POST':
		form = BuddyRequestForm(request.POST, instance=buddy_request)
		form.fields['user'].required = False
		form.fields['creation_time'].required = False
		if form.is_valid():
			form.instance.user = request.user
			form.save()
			return redirect('buddy_system')
		else:
			dictionary['form'] = form
			return render(request, 'buddy_system/buddy_request.html', dictionary)
	else:
		form = BuddyRequestForm(instance=buddy_request)
		form.user = request.user
		dictionary['form'] = form
		return render(request, 'buddy_system/buddy_request.html', dictionary)


@login_required
@require_GET
def delete_buddy_request(request, request_id):
	buddy_request = get_object_or_404(BuddyRequest, id=request_id)

	if buddy_request.replies.count() > 0:
		return HttpResponseBadRequest("You are not allowed to delete a request that has replies.")
	if buddy_request.user != request.user:
		return HttpResponseBadRequest("You are not allowed to delete a request you didn't create.")

	buddy_request.deleted = True
	buddy_request.save(update_fields=['deleted'])
	return redirect('buddy_system')


@login_required
@require_POST
def buddy_request_reply(request, request_id):
	buddy_request = get_object_or_404(BuddyRequest, id=request_id)
	user: User = request.user
	message_content = request.POST['reply_content']

	error_message = check_user_reply_error(buddy_request, user)
	if error_message:
		return HttpResponseBadRequest(error_message)
	elif message_content:
		reply = BuddyRequestMessage()
		reply.buddy_request = buddy_request
		reply.content = message_content
		reply.author = user
		reply.save()
	return redirect('buddy_system')


def check_user_reply_error(buddy_request: BuddyRequest, user: User) -> Optional[str]:
	error_message = None
	try:
		check_policy_to_enter_any_area(user)
	except InactiveUserError:
		error_message = "Your cannot reply to this request because your account has been deactivated"
	except NoActiveProjectsForUserError:
		error_message = "Your cannot reply to this request because you don't have any active projects"
	except PhysicalAccessExpiredUserError:
		error_message = "Your cannot reply to this request because you don't have any active projects"
	except NoPhysicalAccessUserError:
		error_message = "You cannot reply to this request because you do not have access to any areas"
	else:
		if buddy_request.area not in user.accessible_areas():
			error_message = f"You cannot reply to this request because you do not have access to the {buddy_request.area.name}"
	return error_message


def mark_requests_expired():
	BuddyRequest.objects.filter(deleted=False, end__lte=beginning_of_the_day(datetime.now())).update(expired=True)