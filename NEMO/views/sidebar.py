from typing import List

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import render
from django.views.decorators.http import require_GET

from NEMO.decorators import disable_session_expiry_refresh
from NEMO.models import Area, Resource, AreaAccessRecord
from NEMO.views.status_dashboard import create_tool_summary


@login_required
@require_GET
@disable_session_expiry_refresh
def refresh_sidebar_icons(request):
	tool_summary = create_tool_summary()
	area_summary = create_area_summary()
	return render(request, 'refresh_sidebar_icons.html', {'tool_summary': tool_summary, 'area_summary': area_summary})


def create_area_summary():
	areas = Area.objects.filter(requires_reservation=True).only('name','maximum_capacity','reservation_warning','count_staff_in_occupancy')
	# add occupancy and staff occupancy
	areas = areas.annotate(occupancy_staff=Count('areaaccessrecord', filter=Q(areaaccessrecord__end=None, areaaccessrecord__staff_charge=None, areaaccessrecord__customer__is_staff=True)))
	areas = areas.annotate(occupancy=Count('areaaccessrecord', filter=Q(areaaccessrecord__end=None, areaaccessrecord__staff_charge=None)))
	unavailable_resources = Resource.objects.filter(available=False).prefetch_related('dependent_areas')
	occupants: List[AreaAccessRecord] = AreaAccessRecord.objects.filter(end=None, staff_charge=None).prefetch_related('area', 'customer')
	result = {}
	for area in areas:
		result[area.id] = {
			'name': area.name,
			'id': area.id,
			'maximum_capacity': area.maximum_capacity,
			'warning_capacity': area.warning_capacity(),
			'danger_capacity': area.danger_capacity(),
			'count_staff_in_occupancy': area.count_staff_in_occupancy,
			'occupancy_count': area.occupancy if area.count_staff_in_occupancy else area.occupancy - area.occupancy_staff,
			'occupancy_staff_count': area.occupancy_staff,
			'occupants': '',
			'required_resource_is_unavailable': False,
		}
	# Deal with all the parents
	parent_areas = Area.objects.filter(area_children_set__isnull=False).only('name', 'maximum_capacity')
	for parent_area in parent_areas:
		if parent_area.id not in result:
			result[parent_area.id] = {
				'name': parent_area.name,
				'id': parent_area.id,
				'maximum_capacity': parent_area.maximum_capacity,
				'warning_capacity': parent_area.warning_capacity(),
				'danger_capacity': parent_area.danger_capacity(),
				'count_staff_in_occupancy': parent_area.count_staff_in_occupancy,
				'occupancy_count': parent_area.occupancy() if parent_area.count_staff_in_occupancy else parent_area.occupancy() - parent_area.occupancy_staff(),
				'occupancy_staff_count': parent_area.occupancy_staff(),
				'occupants': '',
				'required_resource_is_unavailable': False,
			}
	for resource in unavailable_resources:
		for area in resource.dependent_areas.all():
			if area.id in result:
				result[area.id]['required_resource_is_unavailable'] = True

	for occupant in occupants:
		# Get ids for area and all the parents (so we can add occupants info on parents)
		area_ids = [area.id for area in occupant.area.self_and_parents()]
		if occupant.customer.is_staff:
			customer_display = f'<span style="color:green">{str(occupant.customer)}</span>'
		elif occupant.customer.is_logged_in_area_without_reservation():
			customer_display = f'<span style="color:red">{str(occupant.customer)}</span>'
		else:
			customer_display = str(occupant.customer)
		for area_id in area_ids:
			if area_id in result:
				result[area_id]['occupants'] += customer_display if not result[area_id]['occupants'] else f'<br>{customer_display}'
	area_summary = list(result.values())
	area_summary.sort(key=lambda x: x['name'])
	return area_summary
