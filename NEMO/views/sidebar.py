from html import escape

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.views.decorators.http import require_GET

from NEMO.decorators import disable_session_expiry_refresh
from NEMO.views.status_dashboard import create_tool_summary, create_area_summary


@login_required
@require_GET
@disable_session_expiry_refresh
def refresh_sidebar_icons(request):
	tool_summary = create_tool_summary()
	area_summary = create_area_summary()
	return HttpResponse(refresh_sidebar_icons_content(tool_summary, area_summary))

def refresh_sidebar_icons_content(tool_summary, area_summary):
	result = "$('#sidebar .sidebar-status-icon').remove();$('#sidebar .sidebar-status-occupancy').remove();"

	for tool in tool_summary:
		if tool['area_requires_reservation']:
			result += f"$('a[data-item-id={tool['id']}][data-item-type=tool]').prepend('<span class=\"glyphicon glyphicon-calendar sidebar-status-icon\" title=\"This tool requires prior reservation of the {tool['area_name']}\"></span> ');"

		if tool['in_use']:
			result += f"$('a[data-item-id={tool['id']}][data-item-type=tool]').append('<span class=\"glyphicon glyphicon-user primary-highlight sidebar-status-icon\" title=\"{tool['user']} is using this tool\"></span>');"

		if tool['delayed_logoff_in_progress']:
			result += f"$('a[data-item-id={tool['id']}][data-item-type=tool]').append('<span class=\"glyphicon glyphicon-time primary-highlight sidebar-status-icon\" title=\"Delayed logoff is in effect for this tool\"></span>');"

		if tool['scheduled_outage']:
			result += f"$('a[data-item-id={tool['id']}][data-item-type=tool]').append('<span class=\"glyphicon glyphicon-time danger-highlight sidebar-status-icon\" title=\"A scheduled outage is in effect for this tool\"></span>');"
		elif tool['scheduled_partial_outage']:
			result += f"$('a[data-item-id={tool['id']}][data-item-type=tool]').append('<span class=\"glyphicon glyphicon-time warning-highlight sidebar-status-icon\" title=\"An optional resource for this tool has an outage in effect\"></span>');"

		if tool['required_resource_is_unavailable']:
			result += f"$('a[data-item-id={tool['id']}][data-item-type=tool]').append('<span class=\"glyphicon glyphicon-leaf danger-highlight sidebar-status-icon\" title=\"This tool is unavailable because a required resource is unavailable\"></span>');"
		elif tool['nonrequired_resource_is_unavailable']:
			result += f"$('a[data-item-id={tool['id']}][data-item-type=tool]').append('<span class=\"glyphicon glyphicon-leaf warning-highlight sidebar-status-icon\" title=\"This tool is operating in a diminished capacity because an optional resource is unavailable\"></span>');"

		if not tool['operational']:
			result += f"$('a[data-item-id={tool['id']}][data-item-type=tool]').append('<span class=\"glyphicon glyphicon-fire danger-highlight sidebar-status-icon\" title=\"This tool is shut down\"></span>');"
		elif tool['problematic']:
			result += f"$('a[data-item-id={tool['id']}][data-item-type=tool]').append('<span class=\"glyphicon glyphicon-wrench warning-highlight sidebar-status-icon\" title=\"This tool requires maintenance\"></span>');"
	for area in area_summary:
		if area.get('required_resource_is_unavailable', None):
			result += f"$('[data-item-id={area['id']}][data-item-type=area]').append('<span class=\"glyphicon glyphicon-leaf danger-highlight sidebar-status-icon\" title=\"This area is unavailable because a required resource is unavailable\"></span>');"
		if area.get('maximum_capacity', None):
			result += f"$('[data-item-id={area['id']}][data-item-type=area]').append('<span class=\"sidebar-status-occupancy\"> -</span>');"
			if area['occupancy_count'] >= area['danger_capacity']:
				result += f"$('[data-item-id={area['id']}][data-item-type=area]').append('<span class=\"glyphicon glyphicon-user danger-highlight sidebar-status-icon\" data-toggle=\"tooltip\" title=\"{escape(area['occupants'])}\"></span>');"
			elif area['occupancy_count'] >= area['warning_capacity']:
				result += f"$('[data-item-id={area['id']}][data-item-type=area]').append('<span class=\"glyphicon glyphicon-user warning-highlight sidebar-status-icon\" data-toggle=\"tooltip\" title=\"{escape(area['occupants'])}\"></span>');"
			else:
				result += f"$('[data-item-id={area['id']}][data-item-type=area]').append('<span class=\"glyphicon glyphicon-user success-highlight sidebar-status-icon\" data-toggle=\"tooltip\" title=\"{escape(area['occupants'])}\"></span>');"

			is_are = "is" if area['occupancy_count'] == 1 else "are"
			person_people = "person" if area['occupancy_count'] == 1 else "people"
			if area['count_staff_in_occupancy']:
				result += f"$('[data-item-id={area['id']}][data-item-type=area]').append('<span class=\"sidebar-status-occupancy\" title=\"There {is_are} {area['occupancy_count']} {person_people} in this area\"> {area['occupancy_count']} / {area['maximum_capacity']}</span>');"
			else:
				result += f"$('[data-item-id={area['id']}][data-item-type=area]').append('<span class=\"sidebar-status-occupancy\" title=\"There {is_are} {area['occupancy_count']} {person_people} in this area (+ {area['occupancy_staff']} staff)\"> {area['occupancy_count']} / {area['maximum_capacity']}</span>');"

	result += "$('.tooltip').remove();$('span[data-toggle~=\"tooltip\"]').tooltip({container: 'body', 'html': true});"
	return result