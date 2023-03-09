from django.contrib import messages
from django.db.models import F, Q
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from NEMO.decorators import staff_member_required
from NEMO.exceptions import ProjectChargeException
from NEMO.models import Area, AreaAccessRecord, Project, StaffCharge, UsageEvent, User
from NEMO.policy import policy_class as policy
from NEMO.utilities import (
	BasicDisplayTable,
	export_format_datetime,
	extract_optional_beginning_and_end_dates,
	get_month_timeframe,
	month_list,
)
from NEMO.views.area_access import load_areas_for_use_in_template
from NEMO.views.customization import ApplicationCustomization


@staff_member_required
@require_GET
def remote_work(request):
	if request.GET.get("start") or request.GET.get("end"):
		start_date, end_date = extract_optional_beginning_and_end_dates(request.GET, date_only=True)
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
	usage_events = UsageEvent.objects.filter(operator__is_staff=True).exclude(operator=F("user"))
	s_charges = StaffCharge.objects.filter()
	if start_date:
		usage_events = usage_events.filter(start__gte=start_date)
		s_charges = s_charges.filter(start__gte=start_date)
	if end_date:
		usage_events = usage_events.filter(start__lte=end_date)
		s_charges = s_charges.filter(start__lte=end_date)
	if operator:
		usage_events = usage_events.exclude(~Q(operator_id=operator.id))
		s_charges = s_charges.exclude(~Q(staff_member_id=operator.id))
	if project:
		usage_events = usage_events.filter(project=project)
		s_charges = s_charges.filter(project=project)

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
					START: usage.start,
					END: usage.end,
					PROJECT: usage.project,
				}
			)
		for staff_charge in s_charges:
			for access in staff_charge.areaaccessrecord_set.all():
				table_result.add_row(
					{
						ID: access.area.id,
						TYPE: "Area Access",
						ITEM: access.area,
						STAFF: staff_charge.staff_member,
						CUSTOMER: access.customer,
						START: access.start,
						END: access.end,
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
					START: staff_charge.start,
					END: staff_charge.end,
					PROJECT: staff_charge.project,
				}
			)
		response = table_result.to_csv()
		filename = f"remote_work_{export_format_datetime(start_date, t_format=False)}_to_{export_format_datetime(end_date, t_format=False)}.csv"
		response["Content-Disposition"] = f'attachment; filename="{filename}"'
		return response
	dictionary = {
		"usage": usage_events,
		"staff_charges": s_charges,
		"staff_list": User.objects.filter(is_staff=True),
		"project_list": Project.objects.filter(active=True),
		"start_date": start_date,
		"end_date": end_date,
		"month_list": month_list(),
		"selected_staff": operator.id if operator else "all staff",
		"selected_project": project.id if project else "all projects",
		"remote_work_validation": ApplicationCustomization.get_bool("remote_work_validation"),
	}
	return render(request, "remote_work/remote_work.html", dictionary)


@staff_member_required
@require_POST
def validate_staff_charge(request, staff_charge_id):
	staff_charge = get_object_or_404(StaffCharge, id=staff_charge_id)
	staff_charge.validated = True
	staff_charge.save()
	return HttpResponse()


@staff_member_required
@require_POST
def validate_usage_event(request, usage_event_id):
	usage_event = get_object_or_404(UsageEvent, id=usage_event_id)
	usage_event.validated = True
	usage_event.save()
	return HttpResponse()


@staff_member_required
@require_GET
def staff_charges(request):
	staff_member: User = request.user
	staff_charge: StaffCharge = staff_member.get_staff_charge()
	dictionary = dict()
	if staff_charge:
		try:
			dictionary["staff_charge"] = staff_charge
			# Create dictionary of charges for time, tool and areas
			charges = [{"type": "Start time charge", "start": staff_charge.start, "end": staff_charge.end}]
			for area_charge in AreaAccessRecord.objects.filter(staff_charge_id=staff_charge.id):
				charges.append(
					{
						"type": area_charge.area.name + " access",
						"start": area_charge.start,
						"end": area_charge.end,
						"class": "primary-highlight",
					}
				)
			for tool_charge in UsageEvent.objects.filter(
					operator=staff_member, user=staff_charge.customer, start__gt=staff_charge.start
			):
				charges.append(
					{
						"type": tool_charge.tool.name + " usage",
						"start": tool_charge.start,
						"end": tool_charge.end,
						"class": "warning-highlight",
					}
				)
			charges.sort(key=lambda x: x["start"], reverse=True)
			dictionary["charges"] = charges

			area_access_record = AreaAccessRecord.objects.get(staff_charge=staff_charge.id, end=None)
			dictionary["area"] = area_access_record.area
			return render(request, "staff_charges/end_area_charge.html", dictionary)
		except AreaAccessRecord.DoesNotExist:
			dictionary["user_accessible_areas"], dictionary["areas"] = load_areas_for_use_in_template(staff_member)
			return render(request, "staff_charges/change_status.html", dictionary)
	error = None
	customer = None
	try:
		customer = User.objects.get(id=request.GET["customer"])
	except:
		pass
	if customer:
		if customer.active_project_count() > 0:
			dictionary["customer"] = customer
			return render(request, "staff_charges/choose_project.html", dictionary)
		else:
			error = str(customer) + " does not have any active projects. You cannot bill staff time to this user."
	users = User.objects.filter(is_active=True).exclude(id=request.user.id)
	dictionary["users"] = users
	dictionary["error"] = error
	return render(request, "staff_charges/new_staff_charge.html", dictionary)


@staff_member_required
@require_POST
def begin_staff_charge(request):
	user: User = request.user
	if user.charging_staff_time():
		return HttpResponseBadRequest("You cannot create a new staff charge when one is already in progress.")
	charge = StaffCharge()
	charge.customer = User.objects.get(id=request.POST["customer"])
	charge.project = Project.objects.get(id=request.POST["project"])
	# Check if we are allowed to bill to project
	try:
		policy.check_billing_to_project(charge.project, charge.customer, charge)
	except ProjectChargeException as e:
		return HttpResponseBadRequest(e.msg)
	charge.staff_member = request.user
	charge.save()
	return redirect(reverse("staff_charges"))


@staff_member_required
@require_POST
def end_staff_charge(request):
	user: User = request.user
	if not user.charging_staff_time():
		return HttpResponseBadRequest("You do not have a staff charge in progress, so you cannot end it.")
	charge = user.get_staff_charge()
	charge.end = timezone.now()
	charge.save()
	try:
		area_access = AreaAccessRecord.objects.get(staff_charge=charge, end=None)
		area_access.end = timezone.now()
		area_access.save()
	except AreaAccessRecord.DoesNotExist:
		pass
	return redirect(reverse("staff_charges"))


@staff_member_required
@require_POST
def begin_staff_area_charge(request):
	user: User = request.user
	charge = user.get_staff_charge()
	if not charge:
		return HttpResponseBadRequest(
			"You do not have a staff charge in progress, so you cannot begin an area access charge."
		)
	if AreaAccessRecord.objects.filter(staff_charge=charge, end=None).count() > 0:
		return HttpResponseBadRequest("You cannot create an area access charge when one is already in progress.")
	try:
		area = Area.objects.get(id=request.POST["area"])
		policy.check_billing_to_project(charge.project, charge.customer, area)
	except ProjectChargeException as e:
		return HttpResponseBadRequest(e.msg)
	except:
		return HttpResponseBadRequest("Invalid area")
	area_access = AreaAccessRecord()
	area_access.area = area
	area_access.staff_charge = charge
	area_access.customer = charge.customer
	area_access.project = charge.project
	area_access.save()
	return redirect(reverse("staff_charges"))


@staff_member_required
@require_POST
def end_staff_area_charge(request):
	user: User = request.user
	charge = user.get_staff_charge()
	if not charge:
		return HttpResponseBadRequest("You do not have a staff charge in progress, so you cannot end area access.")
	area_access = AreaAccessRecord.objects.get(staff_charge=charge, end=None)
	area_access.end = timezone.now()
	area_access.save()
	return redirect(reverse("staff_charges"))


@staff_member_required
@require_POST
def edit_staff_charge_note(request):
	user: User = request.user
	charge: StaffCharge = user.get_staff_charge()
	if charge:
		message = f"The charge note was {'updated' if charge.note else 'saved'}"
		charge.note = request.POST.get("staff_charge_note")
		charge.save(update_fields=["note"])
		messages.success(request, message)
	return HttpResponse()
