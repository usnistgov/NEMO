from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponseBadRequest
from django.shortcuts import render, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from NEMO.models import User, StaffCharge, AreaAccessRecord, Project, Area


@staff_member_required(login_url=None)
@require_GET
def staff_charges(request):
	staff_charge = request.user.get_staff_charge()
	if staff_charge:
		try:
			area_access_record = AreaAccessRecord.objects.get(staff_charge=staff_charge.id, end=None)
			return render(request, 'staff_charges/end_area_charge.html', {'area': area_access_record.area})
		except AreaAccessRecord.DoesNotExist:
			return render(request, 'staff_charges/change_status.html', {'areas': Area.objects.all()})
	error = None
	customer = None
	try:
		customer = User.objects.get(id=request.GET['customer'])
	except:
		pass
	if customer:
		if customer.active_project_count() > 0:
			return render(request, 'staff_charges/choose_project.html', {'customer': customer})
		else:
			error = str(customer) + ' does not have any active projects. You cannot bill staff time to this user.'
	users = User.objects.filter(is_active=True).exclude(id=request.user.id)
	return render(request, 'staff_charges/new_staff_charge.html', {'users': users, 'error': error})


@staff_member_required(login_url=None)
@require_POST
def begin_staff_charge(request):
	if request.user.charging_staff_time():
		return HttpResponseBadRequest('You cannot create a new staff charge when one is already in progress.')
	charge = StaffCharge()
	charge.customer = User.objects.get(id=request.POST['customer'])
	charge.project = Project.objects.get(id=request.POST['project'])
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
