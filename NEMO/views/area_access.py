from datetime import date, timedelta
from time import sleep

from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required, permission_required
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from NEMO.models import Area, AreaAccessRecord, Project, User

from NEMO.utilities import parse_start_and_end_date
from NEMO.views.customization import get_customization


@staff_member_required(login_url=None)
@require_GET
def area_access(request):
	""" Presents a page that displays audit records for all NanoFab areas. """
	today = timezone.now().strftime('%m/%d/%Y')
	yesterday = (timezone.now() - timedelta(days=1)).strftime('%m/%d/%Y')
	dictionary = {
		'today': reverse('area_access') + '?' + urlencode({'start': today, 'end': today}),
		'yesterday': reverse('area_access') + '?' + urlencode({'start': yesterday, 'end': yesterday}),
	}
	try:
		start, end = parse_start_and_end_date(request.GET['start'], request.GET['end'])
		dictionary['start'] = start
		dictionary['end'] = end
		dictionary['access_records'] = AreaAccessRecord.objects.filter(start__gte=start, start__lt=end, staff_charge=None)
	except:
		pass
	return render(request, 'area_access/area_access.html', dictionary)


@staff_member_required(login_url=None)
@require_http_methods(['GET', 'POST'])
def new_area_access_record(request):
	dictionary = {
		'customers': User.objects.filter(is_active=True)
	}
	if request.method == 'GET':
		try:
			customer = User.objects.get(id=request.GET['customer'], is_active=True)
			dictionary['customer'] = customer
			dictionary['areas'] = list(set([access_level.area for access_level in customer.physical_access_levels.all()]))
			if customer.active_project_count() == 0:
				dictionary['error_message'] = '{} does not have any active projects to bill area access'.format(customer)
				return render(request, 'area_access/new_area_access_record.html', dictionary)
			if not dictionary['areas']:
				dictionary['error_message'] = '{} does not have access to any billable NanoFab areas'.format(customer)
				return render(request, 'area_access/new_area_access_record.html', dictionary)
			return render(request, 'area_access/new_area_access_record_details.html', dictionary)
		except:
			pass
		return render(request, 'area_access/new_area_access_record.html', dictionary)
	if request.method == 'POST':
		try:
			user = User.objects.get(id=request.POST['customer'], is_active=True)
			project = Project.objects.get(id=request.POST['project'])
			area = Area.objects.get(id=request.POST['area'])
		except:
			dictionary['error_message'] = 'Your request contained an invalid identifier.'
			return render(request, 'area_access/new_area_access_record.html', dictionary)
		if user.access_expiration is not None and user.access_expiration < timezone.now().date():
			dictionary['error_message'] = '{} does not have access to the {} because the user\'s physical access expired on {}. You must update the user\'s physical access expiration date before creating a new area access record.'.format(user, area.name.lower(), user.access_expiration.strftime('%B %m, %Y'))
			return render(request, 'area_access/new_area_access_record.html', dictionary)
		if not any([access_level.accessible() for access_level in user.physical_access_levels.filter(area=area)]):
			dictionary['error_message'] = '{} does not have a physical access level that allows access to the {} at this time.'.format(user, area.name.lower())
			return render(request, 'area_access/new_area_access_record.html', dictionary)
		if user.billing_to_project():
			dictionary['error_message'] = '{} is already billing area access to another area. The user must log out of that area before entering another.'.format(user)
			return render(request, 'area_access/new_area_access_record.html', dictionary)
		if project not in user.active_projects():
			dictionary['error_message'] = '{} is not authorized to bill that project.'.format(user)
			return render(request, 'area_access/new_area_access_record.html', dictionary)
		if area.required_resources.filter(available=False).exists():
			dictionary['error_message'] = 'The {} is inaccessible because a required resource is unavailable. You must make all required resources for this area available before creating a new area access record.'.format(area.name.lower())
			return render(request, 'area_access/new_area_access_record.html', dictionary)
		record = AreaAccessRecord()
		record.area = area
		record.customer = user
		record.project = project
		record.save()
		dictionary['success'] = '{} is now logged in to the {}.'.format(user, area.name.lower())
		return render(request, 'area_access/new_area_access_record.html', dictionary)


@staff_member_required(login_url=None)
@require_POST
def force_area_logout(request, user_id):
	user = get_object_or_404(User, id=user_id)
	record = user.area_access_record()
	if record is None:
		return HttpResponseBadRequest('That user is not logged into any areas.')
	record.end = timezone.now()
	record.save()
	return HttpResponse()


@login_required
@require_http_methods(['GET', 'POST'])
def change_project(request, new_project=None):
	user: User = request.user
	""" For area access, allow the user to stop billing a project and start billing another project. """
	if request.method == 'GET':
		return render(request, 'area_access/change_project.html')
	old_project = user.billing_to_project()
	if old_project is None:
		dictionary = {
			'error': "There was a problem changing the project you're billing for area access. You must already be billing a project in order to change to another project, however you were not logged in to an area."
		}
		return render(request, 'area_access/change_project.html', dictionary)
	# If we're already billing the requested project then there's nothing to do.
	if old_project.id == new_project:
		return redirect(reverse('landing'))
	new_project = get_object_or_404(Project, id=new_project)
	if new_project not in user.active_projects():
		dictionary = {
			'error': 'You do not have permission to bill that project.'
		}
		return render(request, 'area_access/change_project.html', dictionary)
	# Stop billing the user's initial project
	record = user.area_access_record()
	record.end = timezone.now()
	record.save()
	area = record.area
	# Start billing the user's new project
	record = AreaAccessRecord()
	record.area = area
	record.customer = request.user
	record.project = new_project
	record.save()
	return redirect(reverse('landing'))


@login_required
@require_http_methods(['GET', 'POST'])
def self_log_in(request):
	user: User = request.user
	if not able_to_self_log_in_to_area(user):
		return redirect(reverse('landing'))
	dictionary = {
		'projects': user.active_projects(),
	}
	areas = []
	for access_level in user.physical_access_levels.all():
		unavailable_resources = access_level.area.required_resources.filter(available=False)
		if access_level.accessible() and not unavailable_resources:
			areas.append(access_level.area)
	dictionary['areas'] = areas
	if request.method == 'GET':
		return render(request, 'area_access/self_login.html', dictionary)
	if request.method == 'POST':
		try:
			a = Area.objects.get(id=request.POST['area'])
			p = Project.objects.get(id=request.POST['project'])
			if a in dictionary['areas'] and p in dictionary['projects']:
				AreaAccessRecord.objects.create(area=a, customer=request.user, project=p)
		except:
			pass
		return redirect(reverse('landing'))


@login_required
@require_GET
def self_log_out(request, user_id):
	user = get_object_or_404(User, id=user_id)
	if able_to_self_log_out_of_area(user):
		record = user.area_access_record()
		if record is None:
			return HttpResponseBadRequest('You are not logged into any areas.')
		record.end = timezone.now()
		record.save()
	return redirect(reverse('landing'))


def able_to_self_log_out_of_area(user):
	# 'Self log out' must be enabled
	if not get_customization('self_log_out') == 'enabled':
		return False
	# Check if the user is active
	if not user.is_active:
		return False
	# Check if the user is already in an area.
	if not user.in_area():
		return False
	# Otherwise we are good to log out
	return True


def able_to_self_log_in_to_area(user):
	# 'Self log in' must be enabled
	if not get_customization('self_log_in') == 'enabled':
		return False
	# Check if the user is active
	if not user.is_active:
		return False
	# Check if the user has a billable project
	if user.active_project_count() < 1:
		return False
	# Check if the user is already in an area. If so, the /change_project/ URL can be used to change their project.
	if user.in_area():
		return False
	# Check if the user has any physical access levels
	if not user.physical_access_levels.all().exists():
		return False
	# Check if the user normally has access to this area at the current time
	accessible_areas = []
	for access_level in user.physical_access_levels.all():
		if access_level.accessible():
			accessible_areas.append(access_level.area)
	if not accessible_areas:
		return False
	# Check that the user's physical access has not expired
	if user.access_expiration is not None and user.access_expiration < date.today():
		return False
	# Staff are exempt from the remaining rule checks
	if user.is_staff:
		return True
	# Users may not access an area if a required resource is unavailable,
	# so return true if there exists at least one area they are able to log in to.
	for area in accessible_areas:
		unavailable_resources = area.required_resources.filter(available=False)
		if not unavailable_resources:
			return True
	# No areas are accessible...
	return False
