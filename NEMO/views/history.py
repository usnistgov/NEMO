from typing import List

from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, render
from django.utils.text import capfirst, slugify
from django.views.decorators.http import require_GET

from NEMO.decorators import any_staff_required
from NEMO.models import Account, ActivityHistory, MembershipHistory, Project, User
from NEMO.utilities import BasicDisplayTable, export_format_datetime


@any_staff_required
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
	action_list = BasicDisplayTable()
	action_list.headers = [("date", "Date & time"), ("authorizer", "User"), ("message", "Action")]
	for a in activity:
		message = capfirst(content_type.name) + " "
		if a.action == ActivityHistory.Action.ACTIVATED:
			message += "activated."
		else:
			message += "deactivated."
		action_list.add_row({"date": a.date, "authorizer": str(a.authorizer), "message": message})
	for m in membership:
		message = capfirst(m.child_content_type.name) + ' "' + m.get_child_content_object() + '" '
		if m.action:
			message += "added to"
		else:
			message += "removed from"
		message += " this " + content_type.name + "."
		action_list.add_row({"date": m.date, "authorizer": str(m.authorizer), "message": message})
	for o in ownership:
		message = "This " + content_type.name + " "
		if o.action:
			message += "now"
		else:
			message += "no longer"
		message += " belongs to " + o.parent_content_type.name + ' "' + o.get_parent_content_object() + '".'
		action_list.add_row({"date": o.date, "authorizer": str(o.authorizer), "message": message})
	if apps.is_installed("auditlog"):
		from auditlog.models import LogEntry

		logentries: List[LogEntry] = LogEntry.objects.filter(content_type=content_type, object_id=item_id)
		for log_entry in logentries:
			action_list.add_row(
				{
					"date": log_entry.timestamp,
					"authorizer": str(log_entry.actor),
					"message": audit_log_message(log_entry),
				}
			)
	# Sort the list of actions by date:
	action_list.rows.sort(key=lambda x: x["date"], reverse=True)
	csv_export = bool(request.GET.get("csv", False))
	if csv_export:
		name = slugify(getattr(item, 'name', str(item))).replace("-", "_")
		response = action_list.to_csv()
		filename = f"{item_type}_history_{name}_{export_format_datetime()}.csv"
		response["Content-Disposition"] = f'attachment; filename="{filename}"'
		return response
	return render(request, "history.html", {"action_list": action_list, "name": str(item)})


def audit_log_message(logentry, separator: str = "\n"):
	substrings = []

	for field, values in logentry.changes_dict.items():
		# Try to get verbose field name from the model
		try:
			field = logentry.content_type.model_class()._meta.get_field(field).verbose_name.capitalize()
		except:
			pass
		if isinstance(values, dict) and values["type"] == "m2m":
			# Only case with dict is m2m change
			action = "removed" if values["operation"] == "delete" else "added"
			from_to = "from" if action == "removed" else "to"
			objects = [f'"{obj}"' for obj in values["objects"]]
			were_was = "were" if len(objects) > 1 else "was"
			substring = f"{' & '.join(objects)} {were_was} {action} {from_to} {field}"
		else:
			substring = f"{field} was changed: {values[0]} \u2192 {values[1]}"
		substrings.append(substring)

	return separator.join(substrings)
