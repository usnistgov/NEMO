from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.http import require_GET

from NEMO.decorators import disable_session_expiry_refresh
from NEMO.models import ReservationItemType
from NEMO.views.status_dashboard import create_tool_summary, create_area_summary


@login_required
@require_GET
@disable_session_expiry_refresh
def refresh_sidebar_icons(request, item_type=None):
	area_summary = []
	tool_summary = []
	item_type = ReservationItemType(item_type)
	if item_type == ReservationItemType.NONE:
		tool_summary = create_tool_summary()
		area_summary = create_area_summary()
	elif item_type == ReservationItemType.AREA:
		area_summary = create_area_summary()
	elif item_type == ReservationItemType.TOOL:
		tool_summary = create_tool_summary()

	return render(request, 'refresh_sidebar_icons.html', {'tool_summary':tool_summary, 'area_summary':area_summary})