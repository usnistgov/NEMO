from typing import List, Optional

from django.contrib.auth.decorators import login_required
from django.db.models import Q, QuerySet, Count, Prefetch
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from NEMO.decorators import disable_session_expiry_refresh
from NEMO.model_tree import get_area_model_tree, TreeItem, ModelTreeHelper
from NEMO.models import AreaAccessRecord, Resource, ScheduledOutage, Task, Tool, UsageEvent, User, Area
from NEMO.views.customization import get_customization


@login_required
@require_GET
@disable_session_expiry_refresh
def status_dashboard(request, tab=None):
	"""
	Present a web page to allow users to view the status and usage of all tools.
	"""
	interest = request.GET.get('interest')
	if interest is None:
		area_items, no_occupants = process_area_access_record_with_parents(request.user)
		dictionary = {
			'tab': tab if tab else "occupancy",
			'tool_summary': create_tool_summary(),
			'area_items': area_items,
			'no_occupants': no_occupants,
		}
		return render(request, 'status_dashboard/status_dashboard.html', dictionary)
	elif interest == "tools":
		dictionary = {
			'tool_summary': create_tool_summary(),
		}
		return render(request, 'status_dashboard/tools.html', dictionary)
	elif interest == "occupancy":
		area_items, no_occupants = process_area_access_record_with_parents(request.user)
		dictionary = {
			'area_items': area_items,
			'no_occupants': no_occupants,
		}
		return render(request, 'status_dashboard/occupancy.html', dictionary)


def process_area_access_record_with_parents(user: User):
	show_not_qualified_areas = get_customization('dashboard_display_not_qualified_areas')
	records = AreaAccessRecord.objects.filter(end=None, staff_charge=None).prefetch_related('area')
	if not user.is_staff and show_not_qualified_areas != 'enabled':
		records = records.filter(area__in=user.accessible_areas())
	records = records.prefetch_related('customer', 'project', 'area')
	no_occupants = not records.exists()
	area_items = None
	area_model_tree = get_area_model_tree()
	if not no_occupants:
		areas_and_parents = area_model_tree.get_ancestor_areas(area_model_tree.get_areas([record.area.id for record in records]), include_self=True)
		# Sort to have area without children before others
		areas_and_parents.sort(key=lambda x: f'{x.tree_category}zz' if x.is_leaf else f'{x.tree_category}/aa')
		area_summary = create_area_summary(area_model_tree, False, False)
		area_summary_dict = {area['id']: area for area in area_summary}
		for area_item in areas_and_parents:
			area_item.item = area_summary_dict[area_item.id]
		area_items = area_tree_helper(areas_and_parents, records)
	return area_items, no_occupants


def area_tree_helper(filtered_area: List[TreeItem], records: QuerySet, areas: Optional[List[TreeItem]] = None):
	""" Recursively build a list of areas. The resulting list is meant to be iterated over in a view """
	if areas is None:
		# Get the root areas
		areas = [area for area in filtered_area if area.is_root]
	else:
		yield 'in'

	for area in areas:
		yield area
		children = [child for child in area.children if child in filtered_area]
		if len(children):
			area.leaf = False
			for x in area_tree_helper(filtered_area, records, children):
				yield x
		else:
			area.occupants = records.filter(area__id=area.id)
			area.leaf = True
	yield 'out'


def create_tool_summary():
	tools = Tool.objects.filter(visible=True).prefetch_related(Prefetch('_requires_area_access', queryset=Area.objects.all().only('name')))
	tasks = Task.objects.filter(cancelled=False, resolved=False, tool__visible=True).prefetch_related('tool')
	unavailable_resources = Resource.objects.filter(available=False).prefetch_related('fully_dependent_tools', 'partially_dependent_tools')
	# also check for visibility on the parent if there is one (alternate tool are hidden)
	usage_events = UsageEvent.objects.filter(Q(end=None, tool__visible=True)|Q(end=None, tool__parent_tool__visible=True)).prefetch_related('operator', 'user', 'tool')
	scheduled_outages = ScheduledOutage.objects.filter(start__lte=timezone.now(), end__gt=timezone.now())
	tool_summary = merge(tools, tasks, unavailable_resources, usage_events, scheduled_outages)
	tool_summary = list(tool_summary.values())
	tool_summary.sort(key=lambda x: x['name'])
	return tool_summary


def create_area_summary(area_model_tree: ModelTreeHelper=None, add_resources=True, add_occupants=True):
	if area_model_tree is None:
		area_model_tree = get_area_model_tree()
	area_items = area_model_tree.items.values()
	# add occupancy and staff occupancy
	areas_with_counts = area_model_tree.leaves_queryset.only('name').annotate(occupancy_staff=Count('areaaccessrecord', filter=Q(areaaccessrecord__end=None, areaaccessrecord__staff_charge=None, areaaccessrecord__customer__is_staff=True)))
	areas_with_counts = areas_with_counts.annotate(occupancy=Count('areaaccessrecord', filter=Q(areaaccessrecord__end=None, areaaccessrecord__staff_charge=None)))
	area_dict = {area.id: area for area in areas_with_counts}
	result = {}
	for area in area_items:
		occupancy = area_dict[area.id].occupancy if area.is_leaf else sum(area_dict[child.id].occupancy for child in area.descendants if child.is_leaf)
		occupancy_staff = area_dict[area.id].occupancy_staff if area.is_leaf else sum(area_dict[child.id].occupancy_staff for child in area.descendants if child.is_leaf)
		result[area.id] = {
			'name': area.name,
			'id': area.id,
			'maximum_capacity': area.maximum_capacity,
			'warning_capacity': area.item.warning_capacity(),
			'danger_capacity': area.item.danger_capacity(),
			'count_staff_in_occupancy': area.count_staff_in_occupancy,
			'occupancy_count': occupancy if area.count_staff_in_occupancy else occupancy-occupancy_staff,
			'occupancy': occupancy,
			'occupancy_staff': occupancy_staff,
			'occupants': '',
			'required_resource_is_unavailable': False,
		}

	if add_resources:
		unavailable_resources = Resource.objects.filter(available=False).prefetch_related('dependent_areas')
		for resource in unavailable_resources:
			for area in resource.dependent_areas.all():
				if area.id in result:
					result[area.id]['required_resource_is_unavailable'] = True

	if add_occupants:
		occupants: List[AreaAccessRecord] = AreaAccessRecord.objects.filter(end=None, staff_charge=None).prefetch_related('area', 'customer')
		for occupant in occupants:
			# Get ids for area and all the parents (so we can add occupants info on parents)
			area_ids = area_model_tree.get_area(occupant.area.id).ancestor_ids(True)
			if occupant.customer.is_staff:
				customer_display = f'<span class="success-highlight">{str(occupant.customer)}</span>'
			elif occupant.customer.is_logged_in_area_without_reservation():
				customer_display = f'<span class="danger-highlight">{str(occupant.customer)}</span>'
			else:
				customer_display = str(occupant.customer)
			for area_id in area_ids:
				if area_id in result:
					result[area_id]['occupants'] += customer_display if not result[area_id]['occupants'] else f'<br>{customer_display}'
	area_summary = list(result.values())
	area_summary.sort(key=lambda x: x['name'])
	return area_summary


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
