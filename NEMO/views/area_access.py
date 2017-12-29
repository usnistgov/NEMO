from datetime import timedelta, date
from time import sleep

from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required, permission_required
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, render, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode
from django.views.decorators.http import require_POST, require_GET, require_http_methods

from NEMO.models import AreaAccessRecord, Project, User, Door, PhysicalAccessType, Area, PhysicalAccessLog
from NEMO.tasks import postpone
from NEMO.utilities import parse_start_and_end_date


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


@login_required
@permission_required('NEMO.add_areaaccessrecord')
@require_GET
def welcome_screen(request, door_id):
	door = get_object_or_404(Door, id=door_id)
	return render(request, 'area_access/welcome_screen.html', {'area': door.area, 'door': door})


@login_required
@permission_required('NEMO.change_areaaccessrecord')
@require_GET
def farewell_screen(request, door_id):
	door = get_object_or_404(Door, id=door_id)
	return render(request, 'area_access/farewell_screen.html', {'area': door.area, 'door': door})


@login_required
@permission_required('NEMO.add_areaaccessrecord')
@require_POST
def login_to_area(request, door_id):
	door = get_object_or_404(Door, id=door_id)

	badge_number = request.POST.get('badge_number', '')
	if badge_number == '':
		return render(request, 'area_access/badge_not_found.html')
	try:
		badge_number = int(badge_number)
		user = User.objects.get(badge_number=badge_number)
	except (User.DoesNotExist, ValueError):
		return render(request, 'area_access/badge_not_found.html')

	log = PhysicalAccessLog()
	log.user = user
	log.door = door
	log.time = timezone.now()
	log.result = PhysicalAccessType.DENY  # Assume the user does not have access

	# Check if the user is active
	if not user.is_active:
		log.details = "This user is not active, preventing them from entering any access controlled areas."
		log.save()
		return render(request, 'area_access/inactive.html')

	# Check if the user has any physical access levels
	if not user.physical_access_levels.all().exists():
		log.details = "This user does not belong to ANY physical access levels."
		log.save()
		message = "You have not been granted physical access to any NanoFab area. Please visit the User Office if you believe this is an error."
		return render(request, 'area_access/physical_access_denied.html', {'message': message})

	# Check if the user normally has access to this door at the current time
	if not any([access_level.accessible() for access_level in user.physical_access_levels.filter(area=door.area)]):
		log.details = "This user is not assigned to a physical access level that allows access to this door at this time."
		log.save()
		message = "You do not have access to this area of the NanoFab at this time. Please visit the User Office if you believe this is an error."
		return render(request, 'area_access/physical_access_denied.html', {'message': message})

	# Check that the user's physical access has not expired
	if user.access_expiration is not None and user.access_expiration < date.today():
		log.details = "This user was blocked from this physical access level because their physical access has expired."
		log.save()
		message = "Your physical access to the NanoFab has expired. Have you completed your safety training within the last year? Please visit the User Office to renew your access."
		return render(request, 'area_access/physical_access_denied.html', {'message': message})

	# Users may not access an area if a required resource is unavailable.
	# Staff are exempt from this rule.
	unavailable_resources = door.area.required_resources.filter(available=False)
	if unavailable_resources and not user.is_staff:
		log.details = "The user was blocked from entering this area because a required resource was unavailable."
		log.save()
		return render(request, 'area_access/resource_unavailable.html', {'unavailable_resources': unavailable_resources})

	# Users must have at least one billable project in order to enter an area.
	if user.active_project_count() == 0:
		log.details = "The user has no active projects, preventing them from entering an access controlled area."
		log.save()
		return render(request, 'area_access/no_active_projects.html')

	current_area_access_record = user.area_access_record()
	if current_area_access_record and current_area_access_record.area == door.area:
		# No log entry necessary here because all validation checks passed.
		# The log entry is captured when the subsequent choice is made by the user.
		return render(request, 'area_access/already_logged_in.html', {'area': door.area, 'project': current_area_access_record.project, 'badge_number': user.badge_number})

	previous_area = None
	if user.active_project_count() == 1:
		log.result = PhysicalAccessType.ALLOW
		log.save()

		# Automatically log the user out of any previous area before logging them in to the new area.
		if user.in_area():
			previous_area_access_record = user.area_access_record()
			previous_area_access_record.end = timezone.now()
			previous_area_access_record.save()
			previous_area = previous_area_access_record.area

		record = AreaAccessRecord()
		record.area = door.area
		record.customer = user
		record.project = user.active_projects()[0]
		record.save()
		unlock_door(door)
		return render(request, 'area_access/login_success.html', {'area': door.area, 'name': user.first_name, 'project': record.project, 'previous_area': previous_area})
	elif user.active_project_count() > 1:
		project_id = request.POST.get('project_id')
		if project_id:
			project = get_object_or_404(Project, id=project_id)
			if project not in user.active_projects():
				log.details = "The user attempted to bill the project named {}, but they are not a member of that project.".format(project.name)
				log.save()
				message = "You are not authorized to bill this project."
				return render(request, 'area_access/physical_access_denied.html', {'message': message})
			log.result = PhysicalAccessType.ALLOW
			log.save()

			# Automatically log the user out of any previous area before logging them in to the new area.
			if user.in_area():
				previous_area_access_record = user.area_access_record()
				previous_area_access_record.end = timezone.now()
				previous_area_access_record.save()
				previous_area = previous_area_access_record.area

			record = AreaAccessRecord()
			record.area = door.area
			record.customer = user
			record.project = project
			record.save()
			unlock_door(door)
			return render(request, 'area_access/login_success.html', {'area': door.area, 'name': user.first_name, 'project': record.project, 'previous_area': previous_area})
		else:
			# No log entry necessary here because all validation checks passed, and the user must indicate which project
			# the wish to login under. The log entry is captured when the subsequent choice is made by the user.
			return render(request, 'area_access/choose_project.html', {'area': door.area, 'user': user})


@postpone
def unlock_door(door):
	door.interlock.unlock()
	sleep(8)
	door.interlock.lock()
	sleep(3)


@login_required
@permission_required('NEMO.change_areaaccessrecord')
@require_POST
def logout_of_area(request, door_id):
	try:
		badge_number = int(request.POST.get('badge_number', ''))
		user = User.objects.get(badge_number=badge_number)
	except (User.DoesNotExist, ValueError):
		return render(request, 'area_access/badge_not_found.html')
	record = user.area_access_record()
	# Allow the user to log out of any area, even if this is a logout tablet for a different area.
	if record:
		record.end = timezone.now()
		record.save()
		return render(request, 'area_access/logout_success.html', {'area': record.area, 'name': user.first_name})
	else:
		return render(request, 'area_access/not_logged_in.html')


@staff_member_required(login_url=None)
@require_POST
def force_area_logout(request, user_id):
	user = get_object_or_404(User, id=user_id)
	record = user.area_access_record()
	if record is None:
		return HttpResponseBadRequest('That user is not logged into the {}.'.format(record.area))
	record.end = timezone.now()
	record.save()
	return HttpResponse()


@login_required
@permission_required('NEMO.change_areaaccessrecord')
@require_POST
def open_door(request, door_id):
	door = get_object_or_404(Door, id=door_id)
	badge_number = request.POST.get('badge_number', '')
	try:
		badge_number = int(badge_number)
		user = User.objects.get(badge_number=badge_number)
	except (User.DoesNotExist, ValueError):
		return render(request, 'area_access/badge_not_found.html')
	if user.area_access_record() and user.area_access_record().area == door.area:
		log = PhysicalAccessLog(user=user, door=door, time=timezone.now(), result=PhysicalAccessType.ALLOW, details="The user was permitted to enter this area, and already had an active area access record for this area.")
		log.save()
		unlock_door(door)
		return render(request, 'area_access/door_is_open.html')
	return render(request, 'area_access/not_logged_in.html', {'area': door.area})


@login_required
@require_http_methods(['GET', 'POST'])
def change_project(request, new_project=None):
	""" For area access, allow the user to stop billing a project and start billing another project. """
	if request.method == 'GET':
		return render(request, 'area_access/change_project.html')
	old_project = request.user.billing_to_project()
	if old_project is None:
		dictionary = {
			'error': "There was a problem changing the project you're billing for area access. You must already be billing a project in order to change to another project, however you were not logged in to an area."
		}
		return render(request, 'area_access/change_project.html', dictionary)
	# If we're already billing the requested project then there's nothing to do.
	if old_project.id == new_project:
		return redirect(reverse('landing'))
	new_project = get_object_or_404(Project, id=new_project)
	if new_project not in request.user.active_projects():
		dictionary = {
			'error': 'You do not have permission to bill that project.'
		}
		return render(request, 'area_access/change_project.html', dictionary)
	# Stop billing the user's initial project
	record = request.user.area_access_record()
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
