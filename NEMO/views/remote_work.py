from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import F, Q
from django.http import HttpResponse
from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from NEMO.models import UsageEvent, StaffCharge, User, Project
from NEMO.utilities import month_list, get_month_timeframe, parse_start_and_end_date, BasicDisplayTable


@staff_member_required(login_url=None)
@require_GET
def remote_work(request):
	if request.GET.get("start_date") and request.GET.get("end_date"):
		start_date, end_date = parse_start_and_end_date(request.GET.get("start_date"), request.GET.get("end_date"))
	else:
		start_date, end_date = get_month_timeframe()

	operator = request.GET.get("operator")
	if operator:
		if operator == "all staff":
			operator = None
		else:
			operator = get_object_or_404(User, id=operator)
	else:
		operator = request.user

	project = request.GET.get("project")
	if project and project != "all projects":
		project = get_object_or_404(Project, id=project)
	else:
		project = None
	usage_events = UsageEvent.objects.filter(
		operator__is_staff=True, start__gte=start_date, start__lte=end_date
	).exclude(operator=F("user"))
	staff_charges = StaffCharge.objects.filter(start__gte=start_date, start__lte=end_date)
	if operator:
		usage_events = usage_events.exclude(~Q(operator_id=operator.id))
		staff_charges = staff_charges.exclude(~Q(staff_member_id=operator.id))
	if project:
		usage_events = usage_events.filter(project=project)
		staff_charges = staff_charges.filter(project=project)

	csv_export = bool(request.GET.get("csv", False))
	if csv_export:
		table_result = BasicDisplayTable()
		TYPE, ID, ITEM, STAFF, CUSTOMER, PROJECT, START, END = (
			"item_type",
			"item_id",
			"item",
			"staff_member",
			"customer",
			"project",
			"start_date",
			"end_date",
		)
		table_result.headers = [
			(TYPE, "Item Type"),
			(ID, "Item Id"),
			(ITEM, "Item"),
			(STAFF, "Staff"),
			(CUSTOMER, "Customer"),
			(PROJECT, "Project"),
			(START, "Start"),
			(END, "End"),
		]
		for usage in usage_events:
			table_result.add_row(
				{
					ID: usage.tool.id,
					TYPE: "Tool Usage",
					ITEM: usage.tool,
					STAFF: usage.operator,
					CUSTOMER: usage.user,
					START: usage.start.astimezone(timezone.get_current_timezone()).strftime("%m/%d/%Y @ %I:%M %p"),
					END: usage.end.astimezone(timezone.get_current_timezone()).strftime("%m/%d/%Y @ %I:%M %p") if usage.end else "",
					PROJECT: usage.project,
				}
			)
		for staff_charge in staff_charges:
			for access in staff_charge.areaaccessrecord_set.all():
				table_result.add_row(
					{
						ID: access.area.id,
						TYPE: "Area Access",
						ITEM: access.area,
						STAFF: staff_charge.staff_member,
						CUSTOMER: access.customer,
						START: access.start.astimezone(timezone.get_current_timezone()).strftime("%m/%d/%Y @ %I:%M %p"),
						END: access.end.astimezone(timezone.get_current_timezone()).strftime("%m/%d/%Y @ %I:%M %p") if access.end else "",
						PROJECT: access.project,
					}
				)
			table_result.add_row(
				{
					ID: staff_charge.id,
					TYPE: "Staff Charge",
					ITEM: "Staff Charge",
					STAFF: staff_charge.staff_member,
					CUSTOMER: staff_charge.customer,
					START: staff_charge.start.astimezone(timezone.get_current_timezone()).strftime(
						"%m/%d/%Y @ %I:%M %p"
					),
					END: staff_charge.end.astimezone(timezone.get_current_timezone()).strftime("%m/%d/%Y @ %I:%M %p") if staff_charge.end else "",
					PROJECT: staff_charge.project,
				}
			)
		response = table_result.to_csv()
		filename = f"remote_work_{start_date.strftime('%m_%d_%Y')}_to_{end_date.strftime('%m_%d_%Y')}.csv"
		response["Content-Disposition"] = f'attachment; filename="{filename}"'
		return response
	dictionary = {
		"usage": usage_events,
		"staff_charges": staff_charges,
		"staff_list": User.objects.filter(is_staff=True),
		"project_list": Project.objects.filter(active=True),
		"start_date": start_date,
		"end_date": end_date,
		"month_list": month_list(),
		"selected_staff": operator.id if operator else "all staff",
		"selected_project": project.id if project else "all projects",
	}
	return render(request, "remote_work.html", dictionary)


@staff_member_required(login_url=None)
@require_POST
def validate_staff_charge(request, staff_charge_id):
	staff_charge = get_object_or_404(StaffCharge, id=staff_charge_id)
	staff_charge.validated = True
	staff_charge.save()
	return HttpResponse()


@staff_member_required(login_url=None)
@require_POST
def validate_usage_event(request, usage_event_id):
	usage_event = get_object_or_404(UsageEvent, id=usage_event_id)
	usage_event.validated = True
	usage_event.save()
	return HttpResponse()
