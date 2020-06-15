from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from NEMO.decorators import disable_session_expiry_refresh
from NEMO.models import AreaAccessRecord, Resource, ScheduledOutage, Task, Tool, UsageEvent, User
from NEMO.views.customization import get_customization


@login_required
@require_GET
@disable_session_expiry_refresh
def status_dashboard(request, tab=None):
	"""
	Present a web page to allow users to view the status and usage of all tools.
	"""
	interest = request.GET.get('interest')
	user: User = request.user
	show_not_qualified_areas = get_customization('dashboard_display_not_qualified_areas')
	if interest is None:
		areas = AreaAccessRecord.objects.filter(end=None, staff_charge=None)
		if show_not_qualified_areas != 'enabled':
			areas = areas.filter(area__in=user.accessible_areas())
		dictionary = {
			'tab': tab if tab else "occupancy",
			'tool_summary': create_tool_summary(),
			'facility_occupants': areas.prefetch_related('customer', 'project', 'area'),
		}
		return render(request, 'status_dashboard/status_dashboard.html', dictionary)
	elif interest == "tools":
		dictionary = {
			'tool_summary': create_tool_summary(),
		}
		return render(request, 'status_dashboard/tools.html', dictionary)
	elif interest == "occupancy":
		areas = AreaAccessRecord.objects.filter(end=None, staff_charge=None)
		if show_not_qualified_areas != 'enabled':
			areas = areas.filter(area__in=user.accessible_areas())
		dictionary = {
			'facility_occupants': areas.prefetch_related('customer', 'project', 'area'),
		}
		return render(request, 'status_dashboard/occupancy.html', dictionary)


def create_tool_summary():
	tools = Tool.objects.filter(visible=True)
	tasks = Task.objects.filter(cancelled=False, resolved=False, tool__visible=True).prefetch_related('tool')
	unavailable_resources = Resource.objects.filter(available=False).prefetch_related('fully_dependent_tools', 'partially_dependent_tools')
	# also check for visibility on the parent if there is one (alternate tool are hidden)
	usage_events = UsageEvent.objects.filter(Q(end=None, tool__visible=True)|Q(end=None, tool__parent_tool__visible=True)).prefetch_related('operator', 'user', 'tool')
	scheduled_outages = ScheduledOutage.objects.filter(start__lte=timezone.now(), end__gt=timezone.now())
	tool_summary = merge(tools, tasks, unavailable_resources, usage_events, scheduled_outages)
	tool_summary = list(tool_summary.values())
	tool_summary.sort(key=lambda x: x['name'])
	return tool_summary


def merge(tools, tasks, unavailable_resources, usage_events, scheduled_outages):
	result = {}
	tools_with_delayed_logoff_in_effect = [x.tool.tool_or_parent_id() for x in UsageEvent.objects.filter(end__gt=timezone.now())]
	parent_ids = Tool.objects.filter(parent_tool__isnull=False).values_list('parent_tool_id', flat=True)
	for tool in tools:
		result[tool.tool_or_parent_id()] = {
			'name': tool.name_or_child_in_use_name(parent_ids=parent_ids),
			'id': tool.id,
			'user': '',
			'operator': '',
			'in_use': False,
			'in_use_since': '',
			'delayed_logoff_in_progress': tool.tool_or_parent_id() in tools_with_delayed_logoff_in_effect,
			'problematic': False,
			'operational': tool.operational,
			'required_resource_is_unavailable': False,
			'nonrequired_resource_is_unavailable': False,
			'scheduled_outage': False,
			'scheduled_partial_outage': False,
			'area_name': tool.requires_area_access.name if tool.requires_area_access else None,
			'area_requires_reservation': tool.requires_area_access.requires_reservation if tool.requires_area_access else False,
		}
	for task in tasks:
		result[task.tool.id]['problematic'] = True
	for event in usage_events:
		result[event.tool.tool_or_parent_id()]['operator'] = str(event.operator)
		result[event.tool.tool_or_parent_id()]['user'] = str(event.operator)
		if event.user != event.operator:
			result[event.tool.tool_or_parent_id()]['user'] += " on behalf of " + str(event.user)
		result[event.tool.tool_or_parent_id()]['in_use'] = True
		result[event.tool.tool_or_parent_id()]['in_use_since'] = event.start
	for resource in unavailable_resources:
		for tool in resource.fully_dependent_tools.filter(visible=True):
			result[tool.id]['required_resource_is_unavailable'] = True
		for tool in resource.partially_dependent_tools.filter(visible=True):
			result[tool.id]['nonrequired_resource_is_unavailable'] = True
	for outage in scheduled_outages:
		if outage.tool_id and outage.tool.visible:
			result[outage.tool.id]['scheduled_outage'] = True
		elif outage.resource_id:
			for t in outage.resource.fully_dependent_tools.filter(visible=True):
				result[t.id]['scheduled_outage'] = True
			for t in outage.resource.partially_dependent_tools.filter(visible=True):
				result[t.id]['scheduled_partial_outage'] = True
	return result
