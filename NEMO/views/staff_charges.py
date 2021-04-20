from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponseBadRequest
from django.shortcuts import render, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from NEMO.exceptions import ProjectChargeException
from NEMO.models import User, StaffCharge, AreaAccessRecord, Project, Area, UsageEvent
from NEMO.views.area_access import load_areas_for_use_in_template
from NEMO.views.policy import check_billing_to_project


@staff_member_required(login_url=None)
@require_GET
def staff_charges(request):
	staff_member:User = request.user
	staff_charge: StaffCharge = staff_member.get_staff_charge()
	dictionary = dict()
	if staff_charge:
		try:
			dictionary['staff_charge'] = staff_charge
			# Create dictionary of charges for time, tool and areas
			charges = [{'type': 'Start time charge', 'start': staff_charge.start, 'end': staff_charge.end}]
			for area_charge in AreaAccessRecord.objects.filter(staff_charge_id=staff_charge.id):
				charges.append({'type': area_charge.area.name + ' access', 'start': area_charge.start, 'end': area_charge.end, 'class': 'primary-highlight'})
			for tool_charge in UsageEvent.objects.filter(operator=staff_member, user=staff_charge.customer, start__gt=staff_charge.start):
				charges.append({'type': tool_charge.tool.name + ' usage', 'start': tool_charge.start, 'end': tool_charge.end, 'class': 'warning-highlight'})
			charges.sort(key=lambda x: x['start'], reverse=True)
			dictionary['charges'] = charges

			area_access_record = AreaAccessRecord.objects.get(staff_charge=staff_charge.id, end=None)
			dictionary['area'] = area_access_record.area
			return render(request, 'staff_charges/end_area_charge.html', dictionary)
		except AreaAccessRecord.DoesNotExist:
			dictionary['user_accessible_areas'], dictionary['areas'] = load_areas_for_use_in_template(staff_member)
			return render(request, 'staff_charges/change_status.html', dictionary)
	error = None
	customer = None
	try:
		customer = User.objects.get(id=request.GET['customer'])
	except:
		pass
	if customer:
		if customer.active_project_count() > 0:
			dictionary['customer'] = customer
			return render(request, 'staff_charges/choose_project.html', dictionary)
		else:
			error = str(customer) + ' does not have any active projects. You cannot bill staff time to this user.'
	users = User.objects.filter(is_active=True).exclude(id=request.user.id)
	dictionary['users'] = users
	dictionary['error'] = error
	return render(request, 'staff_charges/new_staff_charge.html', dictionary)


@staff_member_required(login_url=None)
@require_POST
def begin_staff_charge(request):
	if request.user.charging_staff_time():
		return HttpResponseBadRequest('You cannot create a new staff charge when one is already in progress.')
	charge = StaffCharge()
	charge.customer = User.objects.get(id=request.POST['customer'])
	charge.project = Project.objects.get(id=request.POST['project'])
	# Check if we are allowed to bill to project
	try:
		check_billing_to_project(charge.project, charge.customer, charge)
	except ProjectChargeException as e:
		return HttpResponseBadRequest(e.msg)
	charge.staff_member = request.user
	charge.save()
	return redirect(reverse('staff_charges'))


@staff_member_required(login_url=None)
@require_POST
def end_staff_charge(request):
	if not request.user.charging_staff_time():
		return HttpResponseBadRequest('You do not have a staff charge in progress, so you cannot end it.')
	charge = request.user.get_staff_charge()
	charge.end = timezone.now()
	charge.save()
	try:
		area_access = AreaAccessRecord.objects.get(staff_charge=charge, end=None)
		area_access.end = timezone.now()
		area_access.save()
	except AreaAccessRecord.DoesNotExist:
		pass
	return redirect(reverse('staff_charges'))


@staff_member_required(login_url=None)
@require_POST
def begin_staff_area_charge(request):
	charge = request.user.get_staff_charge()
	if not charge:
		return HttpResponseBadRequest('You do not have a staff charge in progress, so you cannot begin an area access charge.')
	if AreaAccessRecord.objects.filter(staff_charge=charge, end=None).count() > 0:
		return HttpResponseBadRequest('You cannot create an area access charge when one is already in progress.')
	try:
		area = Area.objects.get(id=request.POST['area'])
		check_billing_to_project(charge.project, charge.customer, area)
	except ProjectChargeException as e:
		return HttpResponseBadRequest(e.msg)
	except:
		return HttpResponseBadRequest('Invalid area')
	area_access = AreaAccessRecord()
	area_access.area = area
	area_access.staff_charge = charge
	area_access.customer = charge.customer
	area_access.project = charge.project
	area_access.save()
	return redirect(reverse('staff_charges'))


@staff_member_required(login_url=None)
@require_POST
def end_staff_area_charge(request):
	charge = request.user.get_staff_charge()
	if not charge:
		return HttpResponseBadRequest('You do not have a staff charge in progress, so you cannot end area access.')
	area_access = AreaAccessRecord.objects.get(staff_charge=charge, end=None)
	area_access.end = timezone.now()
	area_access.save()
	return redirect(reverse('staff_charges'))
