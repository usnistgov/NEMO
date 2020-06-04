from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.http import require_GET

from NEMO.decorators import disable_session_expiry_refresh
from NEMO.models import Area, Resource
from NEMO.views.status_dashboard import create_tool_summary


@login_required
@require_GET
@disable_session_expiry_refresh
def refresh_sidebar_icons(request):
	tool_summary = create_tool_summary()
	area_summary = create_area_summary()
	return render(request, 'refresh_sidebar_icons.html', {'tool_summary': tool_summary, 'area_summary': area_summary})


def create_area_summary():
	areas = Area.objects.filter(requires_reservation=True)
	unavailable_resources = Resource.objects.filter(available=False).prefetch_related('dependent_areas')
	result = {}
	for area in areas:
		result[area.id] = {
			'name': area.name,
			'id': area.id,
			'maximum_capacity': area.maximum_capacity,
			'warning_capacity': area.warning_capacity(),
			'danger_capacity': area.danger_capacity(),
			'occupancy_count': area.occupancy_count(),
			'required_resource_is_unavailable': False,
		}
	for resource in unavailable_resources:
		for area in resource.dependent_areas.all():
			result[area.id]['required_resource_is_unavailable'] = True
	area_summary = list(result.values())
	area_summary.sort(key=lambda x: x['name'])
	return area_summary
