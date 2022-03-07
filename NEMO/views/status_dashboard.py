from datetime import datetime, timedelta
from typing import Dict, List, Optional, Union

from dateutil.relativedelta import relativedelta
from dateutil.rrule import DAILY, rrule
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db.models import F, Prefetch, Q, QuerySet
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods

from NEMO.decorators import disable_session_expiry_refresh, facility_manager_required
from NEMO.forms import StaffAbsenceForm
from NEMO.model_tree import ModelTreeHelper, TreeItem, get_area_model_tree
from NEMO.models import (
	Area,
	AreaAccessRecord,
	ClosureTime,
	Resource,
	ScheduledOutage,
	StaffAbsence,
	StaffAvailability,
	Task,
	Tool,
	UsageEvent,
	User,
)
from NEMO.utilities import (
	BasicDisplayTable,
	as_timezone,
	beginning_of_the_day,
	export_format_datetime,
	format_datetime,
	quiet_int,
)
from NEMO.views.customization import get_customization


@login_required
@require_GET
@disable_session_expiry_refresh
def status_dashboard(request, tab=None):
	"""
	Present a web page to allow users to view the status and usage of all tools.
	"""
	interest = request.GET.get("interest")
	if interest is None:
		csv_export = bool(request.GET.get("csv", False))
		if tab == "staff" and csv_export:
			return get_staff_status(request, csv_export)
		dictionary = {
			"tab": tab if tab else "occupancy",
			"show_staff_status": show_staff_status(request),
			**get_tools_dictionary(),
			**get_occupancy_dictionary(request),
			**get_staff_status(request),
		}
		return render(request, "status_dashboard/status_dashboard.html", dictionary)
	elif interest == "tools":
		return render(request, "status_dashboard/tools.html", get_tools_dictionary())
	elif interest == "occupancy":
		return render(request, "status_dashboard/occupancy.html", get_occupancy_dictionary(request))


def get_tools_dictionary():
	return {"tool_summary": create_tool_summary()}


def get_occupancy_dictionary(request):
	area_items, no_occupants = process_area_access_record_with_parents(request.user)
	return {"area_items": area_items, "no_occupants": no_occupants}


def get_staff_status(request, csv_export=False) -> Union[Dict, HttpResponse]:
	# Timestamp allows us to know which week/month to show. Defaults to current week
	# Everything here is dealing with date/times without timezones to avoid issues with DST etc
	user: User = request.user
	check_past_status = get_customization("dashboard_staff_status_check_past_status")
	check_future_status = get_customization("dashboard_staff_status_check_future_status")
	user_can_check_past_status = not check_past_status or check_past_status == "staffs" and user.is_staff or check_past_status == "managers" and user.is_facility_manager
	user_can_check_future_status = not check_future_status or check_future_status == "staffs" and user.is_staff or check_future_status == "managers" and user.is_facility_manager
	view = request.GET.get("view", "week")
	now_timestamp = datetime.now().timestamp()
	timestamp = quiet_int(request.GET.get("timestamp", now_timestamp), now_timestamp)
	requested_datetime = datetime.fromtimestamp(timestamp)
	if requested_datetime.date() < datetime.today().date():
		if not user_can_check_past_status:
			# User is looking at past status and is not supposed to
			requested_datetime = datetime.now()
	elif requested_datetime.date() >= (datetime.today() + timedelta(days=1)).date():
		if not user_can_check_future_status:
			# User is looking at future status and is not supposed to
			requested_datetime = datetime.now()
	today = beginning_of_the_day(requested_datetime, in_local_timezone=False)
	weekdays_only = get_customization("dashboard_staff_status_weekdays_only")
	first_day = (
		today.isoweekday()
		if not weekdays_only and get_customization("dashboard_staff_status_first_day_of_week") == "0"
		else today.weekday()
	)
	start = today.replace(day=1) if view == "month" else today - timedelta(days=first_day)
	end_delta = relativedelta(months=1) if view == "month" else timedelta(weeks=1)
	end = start + end_delta - timedelta(days=1)
	# If we are only showing weekdays, we have to subtract 2 days from the end of the week. Only applies to week view
	if view == "week" and weekdays_only:
		end = end - timedelta(days=2)
	# Reset timestamp to be right in the middle of the period
	timestamp = int((start + timedelta(days=(end - start).days/2)).timestamp())
	staffs = StaffAvailability.objects.all()
	staffs.query.add_ordering(F("category").asc(nulls_last=True))
	staffs.query.add_ordering(F("staff_member__first_name").asc())
	days = rrule(DAILY, dtstart=start, until=end)
	staff_date_format = get_customization("dashboard_staff_status_date_format")
	if csv_export:
		return export_staff_status(request, staffs, days, start, end, staff_date_format)
	return {
		"staff_date_format": staff_date_format,
		"staff_absences": staff_absences_dict(staffs, days, start, end),
		"closure_times": closures_dict(days, start, end),
		"staffs": staffs,
		"days": days,
		"days_length": (end - start).days + 1,
		"page_timestamp": timestamp,
		"page_view": view,
		# Using end delta here (=/- 1 week or 1 month) to set previous and next
		"prev": int((start - end_delta).timestamp()) if user_can_check_past_status else None,
		"next": int((end + end_delta).timestamp()) if user_can_check_future_status else None,
	}


@facility_manager_required
@require_http_methods(["GET", "POST"])
def create_staff_absence(request, absence_id=None):
	try:
		absence = StaffAbsence.objects.get(pk=absence_id)
	except (StaffAbsence.DoesNotExist, ValueError):
		absence = StaffAbsence()
		# Set the staff if we were given its id
		try:
			staff_id = request.GET.get("staff_id", None)
			if staff_id:
				absence.staff_member = StaffAvailability.objects.get(pk=staff_id)
		except (StaffAvailability.DoesNotExist, ValueError):
			pass
	form = StaffAbsenceForm(request.POST or None, instance=absence)
	timestamp = request.GET.get("timestamp", "")
	view = request.GET.get("view", "")
	if request.POST and form.is_valid():
		form.save()
		return HttpResponse()
	dictionary = {"form": form, "staff_members": StaffAvailability.objects.all(), "page_timestamp": timestamp, "page_view": view}
	return render(request, "status_dashboard/staff_absence.html", dictionary)


@facility_manager_required
@require_GET
def delete_staff_absence(request, absence_id):
	absence = get_object_or_404(StaffAbsence, id=absence_id)
	absence.delete()
	timestamp = request.GET.get("timestamp", "")
	view = request.GET.get("view", "")
	url = reverse("status_dashboard_tab", args=["staff"])
	return redirect(f"{url}?timestamp={timestamp}&view={view}")


def staff_absences_dict(staffs, days, start, end):
	dictionary = {staff.id: {} for staff in staffs}
	absences = StaffAbsence.objects.filter(start_date__lte=end, end_date__gte=start).order_by("creation_time")
	for staff_absence in absences:
		for day in days:
			# comparing dates here so no timezone issues (dates don't have timezones)
			if staff_absence.start_date <= day.date() <= staff_absence.end_date:
				dictionary[staff_absence.staff_member.id][day.day] = staff_absence
	return dictionary


def closures_dict(days, start, end):
	dictionary = {}
	closure_times = ClosureTime.objects.filter(start_time__lte=end, end_time__gte=start)
	for closure_time in closure_times:
		for day in days:
			if as_timezone(closure_time.start_time).date() <= day.date() <= as_timezone(closure_time.end_time).date():
				dictionary[day.day] = closure_time
	return dictionary


@facility_manager_required
def export_staff_status(request, staffs, days, start, end, staff_date_format) -> HttpResponse:
	table_result = BasicDisplayTable()
	table_result.add_header(("staff", ""))
	# Add headers for each day
	for day in days:
		table_result.add_header((day.day, format_datetime(day, staff_date_format, as_current_timezone=False)))
	staff_absences = staff_absences_dict(staffs, days, start, end)
	closure_times = closures_dict(days, start, end)
	category = ""
	for staff in staffs:
		if staff.category != category:
			category = staff.category or "Other"
			# Add a whole row for the category
			table_result.add_row({"staff": category})
		# Add a row for each staff member
		staff_row = {"staff": staff.staff_member.get_name()}
		for day in days:
			staff_row[day.day] = staff.weekly_availability("In", "Out").get(day.weekday())
		for staff_id, absence_dict in staff_absences.items():
			if staff.id == staff_id:
				for day_index, absence in absence_dict.items():
					staff_row[day_index] = absence.absence_type.name + f" {absence.description or ''}"
		for day_index, closure_time in closure_times.items():
			staff_row[day_index] = f"Closed: {closure_time.closure.name}"
		table_result.add_row(staff_row)
	response = table_result.to_csv()
	filename = f"staff_status_{export_format_datetime(start, t_format=False)}_to_{export_format_datetime(end, t_format=False)}.csv"
	response["Content-Disposition"] = f'attachment; filename="{filename}"'
	return response


def show_staff_status(request):
	if not settings.ALLOW_CONDITIONAL_URLS:
		return False
	dashboard_staff_status_staff_only = get_customization("dashboard_staff_status_staff_only")
	return StaffAvailability.objects.exists() and (not dashboard_staff_status_staff_only or request.user.is_staff)


def process_area_access_record_with_parents(user: User):
	show_not_qualified_areas = get_customization("dashboard_display_not_qualified_areas")
	records = AreaAccessRecord.objects.filter(end=None, staff_charge=None)
	if not user.is_staff and show_not_qualified_areas != "enabled":
		records = records.filter(area__in=user.accessible_areas())
	records = records.prefetch_related("customer", "project", "area")
	no_occupants = not records.exists()
	area_items = None
	area_model_tree = get_area_model_tree()
	if not no_occupants:
		areas_and_parents = area_model_tree.get_ancestor_areas(
			area_model_tree.get_areas([record.area.id for record in records]), include_self=True
		)
		# Sort to have area without children before others
		areas_and_parents.sort(key=lambda x: f"{x.tree_category}zz" if x.is_leaf else f"{x.tree_category}/aa")
		area_summary = create_area_summary(
			area_tree=area_model_tree, add_resources=False, add_outages=False, add_occupants=True
		)
		area_summary_dict = {area["id"]: area for area in area_summary}
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
		yield "in"

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
	yield "out"


def create_tool_summary():
	tools = Tool.objects.filter(visible=True).prefetch_related(
		Prefetch("_requires_area_access", queryset=Area.objects.all().only("name"))
	)
	tasks = Task.objects.filter(cancelled=False, resolved=False, tool__visible=True).prefetch_related("tool")
	unavailable_resources = Resource.objects.filter(available=False).prefetch_related(
		"fully_dependent_tools", "partially_dependent_tools"
	)
	# also check for visibility on the parent if there is one (alternate tool are hidden)
	usage_events = UsageEvent.objects.filter(
		Q(end=None, tool__visible=True) | Q(end=None, tool__parent_tool__visible=True)
	).prefetch_related("operator", "user", "tool")
	scheduled_outages = ScheduledOutage.objects.filter(
		start__lte=timezone.now(), end__gt=timezone.now(), area__isnull=True
	)
	tool_summary = merge(tools, tasks, unavailable_resources, usage_events, scheduled_outages)
	tool_summary = list(tool_summary.values())
	tool_summary.sort(key=lambda x: x["name"])
	return tool_summary


def create_area_summary(area_tree: ModelTreeHelper = None, add_resources=True, add_occupants=True, add_outages=True):
	if area_tree is None:
		area_tree = get_area_model_tree()
	area_items = area_tree.items.values()
	result = {}
	for area in area_items:
		result[area.id] = {
			"name": area.name,
			"id": area.id,
			"maximum_capacity": area.maximum_capacity,
			"warning_capacity": area.item.warning_capacity(),
			"danger_capacity": area.item.danger_capacity(),
			"count_staff_in_occupancy": area.count_staff_in_occupancy,
			"count_service_personnel_in_occupancy": area.count_service_personnel_in_occupancy,
			"occupancy_count": 0,
			"occupancy": 0,
			"occupancy_staff": 0,
			"occupancy_service_personnel": 0,
			"occupants": "",
			"required_resource_is_unavailable": False,
			"scheduled_outage": False,
		}

	if add_resources:
		unavailable_resources = Resource.objects.filter(available=False).prefetch_related(
			Prefetch("dependent_areas", queryset=Area.objects.only("id"))
		)
		for resource in unavailable_resources:
			for area in resource.dependent_areas.all():
				if area.id in result:
					result[area.id]["required_resource_is_unavailable"] = True
	if add_outages:
		scheduled_outages = ScheduledOutage.objects.filter(
			start__lte=timezone.now(), end__gt=timezone.now(), tool__isnull=True
		).only("area_id", "resource_id")
		for outage in scheduled_outages:
			if outage.area_id:
				result[outage.area_id]["scheduled_outage"] = True
			elif outage.resource_id:
				for t in outage.resource.dependent_areas.values_list("id", flat=True):
					result[t]["scheduled_outage"] = True

	if add_occupants:
		occupants: List[AreaAccessRecord] = AreaAccessRecord.objects.filter(
			end=None, staff_charge=None
		).prefetch_related(
			Prefetch("customer", queryset=User.objects.all().only("first_name", "last_name", "username", "is_staff"))
		)
		for occupant in occupants:
			# Get ids for area and all the parents (so we can add occupants info on parents)
			area_ids = area_tree.get_area(occupant.area_id).ancestor_ids(include_self=True)
			if occupant.customer.is_staff:
				customer_display = f'<span class="success-highlight">{str(occupant.customer)}</span>'
			elif occupant.customer.is_service_personnel:
				customer_display = f'<span class="warning-highlight">{str(occupant.customer)}</span>'
			elif occupant.customer.is_logged_in_area_without_reservation():
				customer_display = f'<span class="danger-highlight">{str(occupant.customer)}</span>'
			else:
				customer_display = str(occupant.customer)
			for area_id in area_ids:
				if area_id in result:
					result[area_id]["occupancy"] += 1
					if occupant.customer.is_staff:
						result[area_id]["occupancy_staff"] += 1
					if occupant.customer.is_service_personnel:
						result[area_id]["occupancy_service_personnel"] += 1
					if (not occupant.customer.is_staff or result[area_id]["count_staff_in_occupancy"]) and (
							not occupant.customer.is_service_personnel
							or result[area_id]["count_service_personnel_in_occupancy"]
					):
						result[area_id]["occupancy_count"] += 1
					result[area_id]["occupants"] += (
						customer_display if not result[area_id]["occupants"] else f"<br>{customer_display}"
					)
	area_summary = list(result.values())
	area_summary.sort(key=lambda x: x["name"])
	return area_summary


def merge(tools, tasks, unavailable_resources, usage_events, scheduled_outages):
	result = {}
	tools_with_delayed_logoff_in_effect = [
		x.tool.tool_or_parent_id() for x in UsageEvent.objects.filter(end__gt=timezone.now())
	]
	parent_ids = Tool.objects.filter(parent_tool__isnull=False).values_list("parent_tool_id", flat=True)
	for tool in tools:
		result[tool.tool_or_parent_id()] = {
			"name": tool.name_or_child_in_use_name(parent_ids=parent_ids),
			"id": tool.id,
			"user": "",
			"operator": "",
			"in_use": False,
			"in_use_since": "",
			"delayed_logoff_in_progress": tool.tool_or_parent_id() in tools_with_delayed_logoff_in_effect,
			"problematic": False,
			"operational": tool.operational,
			"required_resource_is_unavailable": False,
			"nonrequired_resource_is_unavailable": False,
			"scheduled_outage": False,
			"scheduled_partial_outage": False,
			"area_name": tool.requires_area_access.name if tool.requires_area_access else None,
			"area_requires_reservation": tool.requires_area_access.requires_reservation
			if tool.requires_area_access
			else False,
		}
	for task in tasks:
		result[task.tool.id]["problematic"] = True
	for event in usage_events:
		result[event.tool.tool_or_parent_id()]["operator"] = str(event.operator)
		result[event.tool.tool_or_parent_id()]["user"] = str(event.operator)
		if event.user != event.operator:
			result[event.tool.tool_or_parent_id()]["user"] += " on behalf of " + str(event.user)
		result[event.tool.tool_or_parent_id()]["in_use"] = True
		result[event.tool.tool_or_parent_id()]["in_use_since"] = event.start
	for resource in unavailable_resources:
		for tool in resource.fully_dependent_tools.filter(visible=True):
			result[tool.id]["required_resource_is_unavailable"] = True
		for tool in resource.partially_dependent_tools.filter(visible=True):
			result[tool.id]["nonrequired_resource_is_unavailable"] = True
	for outage in scheduled_outages:
		if outage.tool_id and outage.tool.visible:
			result[outage.tool.id]["scheduled_outage"] = True
		elif outage.resource_id:
			for t in outage.resource.fully_dependent_tools.filter(visible=True):
				result[t.id]["scheduled_outage"] = True
			for t in outage.resource.partially_dependent_tools.filter(visible=True):
				result[t.id]["scheduled_partial_outage"] = True
	return result
