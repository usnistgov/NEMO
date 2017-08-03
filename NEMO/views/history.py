from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.contenttypes.models import ContentType
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, render
from django.utils.text import capfirst
from django.views.decorators.http import require_GET

from NEMO.models import Account, Project, User, ActivityHistory, MembershipHistory


@staff_member_required(login_url=None)
@require_GET
def history(request, item_type, item_id):
	if item_type == "account":
		item = get_object_or_404(Account, id=item_id)
	elif item_type == "project":
		item = get_object_or_404(Project, id=item_id)
	elif item_type == "user":
		item = get_object_or_404(User, id=item_id)
	else:
		return HttpResponseBadRequest("Invalid history type")
	content_type = ContentType.objects.get_for_model(item)
	activity = ActivityHistory.objects.filter(object_id=item_id, content_type__id__exact=content_type.id)
	membership = MembershipHistory.objects.filter(parent_object_id=item_id, parent_content_type__id__exact=content_type.id)
	ownership = MembershipHistory.objects.filter(child_object_id=item_id, child_content_type__id__exact=content_type.id)
	# Iterate over all activity history and membership history for this object.
	action_list = []
	for a in activity:
		message = capfirst(content_type.name) + " "
		if a.action == ActivityHistory.Action.ACTIVATED:
			message += "activated."
		else:
			message += "deactivated."
		action_list.append({'date': a.date, 'authorizer': str(a.authorizer), 'message': message})
	for m in membership:
		message = capfirst(m.child_content_type.name) + " \"" + str(m.child_content_object) + "\" "
		if m.action:
			message += "added to"
		else:
			message += "removed from"
		message += " this " + content_type.name + "."
		action_list.append({'date': m.date, 'authorizer': str(m.authorizer), 'message': message})
	for o in ownership:
		message = "This " + content_type.name + " "
		if o.action:
			message += "now"
		else:
			message += "no longer"
		message += " belongs to " + o.parent_content_type.name + " \"" + o.parent_content_object.name + "\"."
		action_list.append({'date': o.date, 'authorizer': str(o.authorizer), 'message': message})
	# Sort the list of actions by date:
	action_list.sort(key=lambda x: x['date'])
	return render(request, 'history.html', {'action_list': action_list, 'name': str(item)})
