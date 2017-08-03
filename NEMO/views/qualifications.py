from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponseBadRequest, HttpResponse
from django.shortcuts import render, get_object_or_404
from django.views.decorators.http import require_GET, require_POST

from NEMO.models import Tool, MembershipHistory, User


@staff_member_required(login_url=None)
@require_GET
def qualifications(request):
	""" Present a web page to allow staff to qualify or disqualify users on particular tools. """
	users = User.objects.filter(is_active=True)
	tools = Tool.objects.filter(visible=True)
	return render(request, 'qualifications.html', {'users': users, 'tools': tools})


@staff_member_required(login_url=None)
@require_POST
def modify_qualifications(request):
	""" Change the tools that a set of users is qualified to use. """
	action = request.POST.get('action')
	if action != 'qualify' and action != 'disqualify':
		return HttpResponseBadRequest("You must specify that you are qualifying or disqualifying users.")
	users = request.POST.getlist('chosen_user[]') or request.POST.get('chosen_user') or []
	users = User.objects.in_bulk(users)
	if users == {}:
		return HttpResponseBadRequest("You must specify at least one user.")
	tools = request.POST.getlist('chosen_tool[]') or request.POST.get('chosen_tool') or []
	tools = Tool.objects.in_bulk(tools)
	if tools == {}:
		return HttpResponseBadRequest("You must specify at least one tool.")

	for user in users.values():
		original_qualifications = set(user.qualifications.all())
		if action == 'qualify':
			user.qualifications.add(*tools)
		elif action == 'disqualify':
			user.qualifications.remove(*tools)
		current_qualifications = set(user.qualifications.all())
		# Record the qualification changes for each tool:
		added_qualifications = set(current_qualifications) - set(original_qualifications)
		for tool in added_qualifications:
			entry = MembershipHistory()
			entry.authorizer = request.user
			entry.parent_content_object = tool
			entry.child_content_object = user
			entry.action = entry.Action.ADDED
			entry.save()
		removed_qualifications = set(original_qualifications) - set(current_qualifications)
		for tool in removed_qualifications:
			entry = MembershipHistory()
			entry.authorizer = request.user
			entry.parent_content_object = tool
			entry.child_content_object = user
			entry.action = entry.Action.REMOVED
			entry.save()

	if request.POST.get('redirect') == 'true':
		dictionary = {
			'title': 'Success!',
			'heading': 'Success!',
			'content': 'Tool qualifications were successfully modified.',
		}
		return render(request, 'acknowledgement.html', dictionary)
	else:
		return HttpResponse()


@staff_member_required(login_url=None)
@require_GET
def get_qualified_users(request):
	tool = get_object_or_404(Tool, id=request.GET.get('tool_id'))
	users = User.objects.filter(is_active=True)
	dictionary = {
		'tool': tool,
		'users': users,
		'expanded': True
	}
	return render(request, 'tool_control/qualified_users.html', dictionary)
