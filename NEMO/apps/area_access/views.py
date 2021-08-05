from time import sleep

from django.contrib.auth.decorators import login_required, permission_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.template.defaultfilters import linebreaksbr
from django.utils import timezone
from django.utils.formats import localize
from django.views.decorators.http import require_GET, require_POST

from NEMO.exceptions import (
	InactiveUserError,
	NoActiveProjectsForUserError,
	PhysicalAccessExpiredUserError,
	NoPhysicalAccessUserError,
	NoAccessiblePhysicalAccessUserError,
	UnavailableResourcesUserError,
	MaximumCapacityReachedError,
	ReservationRequiredUserError,
	ScheduledOutageInProgressError,
	ProjectChargeException,
)
from NEMO.models import (
	Door,
	PhysicalAccessLog,
	PhysicalAccessType,
	Project,
	User,
	UsageEvent,
	BadgeReader,
)
from NEMO.tasks import postpone
from NEMO.views.area_access import log_out_user, log_in_user_to_area
from NEMO.views.customization import get_customization
from NEMO.views.policy import check_policy_to_enter_this_area, check_policy_to_enter_any_area, check_billing_to_project
from NEMO.views.tool_control import interlock_bypass_allowed


@login_required
@permission_required("NEMO.add_areaaccessrecord")
@require_GET
def welcome_screen(request, door_id):
	door = get_object_or_404(Door, id=door_id)
	reader_id = request.GET.get("reader_id")
	badge_reader = BadgeReader.objects.get(id=reader_id) if reader_id else BadgeReader.default()
	return render(
		request, "area_access/welcome_screen.html", {"area": door.area, "door": door, "badge_reader": badge_reader}
	)


@login_required
@permission_required("NEMO.change_areaaccessrecord")
@require_GET
def farewell_screen(request, door_id):
	door = get_object_or_404(Door, id=door_id)
	reader_id = request.GET.get("reader_id")
	badge_reader = BadgeReader.objects.get(id=reader_id) if reader_id else BadgeReader.default()
	return render(
		request, "area_access/farewell_screen.html", {"area": door.area, "door": door, "badge_reader": badge_reader}
	)


@login_required
@permission_required("NEMO.add_areaaccessrecord")
@require_POST
def login_to_area(request, door_id):
	door = get_object_or_404(Door, id=door_id)

	badge_number = request.POST.get("badge_number")
	bypass_interlock = request.POST.get("bypass", 'False') == 'True'
	if not badge_number:
		return render(request, "area_access/badge_not_found.html")
	try:
		user = User.objects.get(badge_number=badge_number)
	except User.DoesNotExist:
		return render(request, "area_access/badge_not_found.html")

	log = PhysicalAccessLog()
	log.user = user
	log.door = door
	log.time = timezone.now()
	log.result = PhysicalAccessType.DENY  # Assume the user does not have access

	facility_name = get_customization("facility_name")

	# Check policy for entering an area
	try:
		check_policy_to_enter_any_area(user=user)
	except InactiveUserError:
		log.details = "This user is not active, preventing them from entering any access controlled areas."
		log.save()
		return render(request, "area_access/inactive.html")

	except NoActiveProjectsForUserError:
		log.details = "The user has no active projects, preventing them from entering an access controlled area."
		log.save()
		return render(request, "area_access/no_active_projects.html")

	except PhysicalAccessExpiredUserError:
		log.details = "This user was blocked from this physical access level because their physical access has expired."
		log.save()
		message = f"Your physical access to the {facility_name} has expired. Have you completed your safety training within the last year? Please visit the User Office to renew your access."
		return render(request, "area_access/physical_access_denied.html", {"message": message})

	except NoPhysicalAccessUserError:
		log.details = "This user does not belong to ANY physical access levels."
		log.save()
		message = f"You have not been granted physical access to any {facility_name} area. Please visit the User Office if you believe this is an error."
		return render(request, "area_access/physical_access_denied.html", {"message": message})

	max_capacity_reached = False
	reservation_requirement_failed = False
	scheduled_outage_in_progress = False
	# Check policy to enter this area
	try:
		check_policy_to_enter_this_area(area=door.area, user=user)
	except NoAccessiblePhysicalAccessUserError as error:
		if error.access_exception:
			log.details = (
				f"The user was blocked from entering this area because of an exception: {error.access_exception.name}."
			)
			message = f"You do not have access to this area of the {facility_name} due to the following exception: {error.access_exception}. The exception ends on {localize(error.access_exception.end_time.astimezone(timezone.get_current_timezone()))}"
		else:
			log.details = (
				"This user is not assigned to a physical access level that allows access to this door at this time."
			)
			message = f"You do not have access to this area of the {facility_name} at this time. Please visit the User Office if you believe this is an error."
		log.save()
		return render(request, "area_access/physical_access_denied.html", {"message": message})

	except UnavailableResourcesUserError as error:
		log.details = f"The user was blocked from entering this area because a required resource was unavailable [{', '.join(str(resource) for resource in error.resources)}]."
		log.save()
		return render(request, "area_access/resource_unavailable.html", {"unavailable_resources": error.resources})

	except MaximumCapacityReachedError as error:
		# deal with this error after checking if the user is already logged in
		max_capacity_reached = error

	except ScheduledOutageInProgressError as error:
		# deal with this error after checking if the user is already logged in
		scheduled_outage_in_progress = error

	except ReservationRequiredUserError:
		# deal with this error after checking if the user is already logged in
		reservation_requirement_failed = True

	current_area_access_record = user.area_access_record()
	if current_area_access_record and current_area_access_record.area == door.area:
		# No log entry necessary here because all validation checks passed.
		# The log entry is captured when the subsequent choice is made by the user.
		return render(
			request,
			"area_access/already_logged_in.html",
			{
				"area": door.area,
				"project": current_area_access_record.project,
				"badge_number": user.badge_number,
				"reservation_requirement_failed": reservation_requirement_failed,
				"max_capacity_reached": max_capacity_reached,
				"scheduled_outage_in_progress": scheduled_outage_in_progress,
			},
		)

	if scheduled_outage_in_progress:
		log.details = f"The user was blocked from entering this area because the {scheduled_outage_in_progress.area.name} has a scheduled outage in progress."
		log.save()
		message = (
			f"The {scheduled_outage_in_progress.area.name} is inaccessible because a scheduled outage is in progress."
		)
		return render(request, "area_access/physical_access_denied.html", {"message": message})

	if max_capacity_reached:
		log.details = f"The user was blocked from entering this area because the {max_capacity_reached.area.name} has reached its maximum capacity of {max_capacity_reached.area.maximum_capacity} people at a time."
		log.save()
		message = f"The {max_capacity_reached.area.name} has reached its maximum capacity. Please wait for somebody to leave and try again."
		return render(request, "area_access/physical_access_denied.html", {"message": message})

	if reservation_requirement_failed:
		log.details = f"The user was blocked from entering this area because the user does not have a current reservation for the {door.area}."
		log.save()
		message = "You do not have a current reservation for this area. Please make a reservation before trying to access this area."
		return render(request, "area_access/physical_access_denied.html", {"message": message})

	if user.active_project_count() >= 1:
		if user.active_project_count() == 1:
			project = user.active_projects()[0]
		else:
			project_id = request.POST.get("project_id")
			if not project_id:
				# No log entry necessary here because all validation checks passed, and the user must indicate which project
				# the wish to login under. The log entry is captured when the subsequent choice is made by the user.
				return render(request, "area_access/choose_project.html", {"area": door.area, "user": user})
			else:
				project = get_object_or_404(Project, id=project_id)
				try:
					check_billing_to_project(project, user, door.area)
				except ProjectChargeException as e:
					log.details = "The user attempted to bill the project named {} but got error: {}".format(project.name, e.msg)
					log.save()
					return render(request, "area_access/physical_access_denied.html", {"message": e.msg})

		log.result = PhysicalAccessType.ALLOW
		log.save()

		# Automatically log the user out of any previous area before logging them in to the new area.
		previous_area = None
		if user.in_area():
			previous_area = user.area_access_record().area
			log_out_user(user)

		# All policy checks passed so open the door for the user.
		if not door.interlock.unlock():
			if bypass_interlock and interlock_bypass_allowed(user):
				pass
			else:
				return interlock_error("Login", user)

		delay_lock_door(door.id)

		log_in_user_to_area(door.area, user, project)

		return render(
			request,
			"area_access/login_success.html",
			{"area": door.area, "name": user.first_name, "project": project, "previous_area": previous_area},
		)


@postpone
def delay_lock_door(door_id):
	door = Door.objects.get(id=door_id)
	sleep(8)
	door.interlock.lock()


@login_required
@permission_required("NEMO.change_areaaccessrecord")
@require_POST
def logout_of_area(request, door_id):
	badge_number = request.POST.get("badge_number")
	if not badge_number:
		return render(request, "area_access/badge_not_found.html")
	try:
		user = User.objects.get(badge_number=badge_number)
	except User.DoesNotExist:
		return render(request, "area_access/badge_not_found.html")
	record = user.area_access_record()
	if record:
		log_out_user(user)
		busy_tools = UsageEvent.objects.filter(end=None, user=user)
		staff_charge = user.get_staff_charge()
		if busy_tools or staff_charge:
			return render(
				request,
				"area_access/logout_warning.html",
				{
					"area": record.area,
					"name": user.first_name,
					"tools_in_use": busy_tools,
					"staff_charge": staff_charge,
				},
			)
		else:
			return render(request, "area_access/logout_success.html", {"area": record.area, "name": user.first_name})
	else:
		return render(request, "area_access/not_logged_in.html")


@login_required
@permission_required("NEMO.change_areaaccessrecord")
@require_POST
def open_door(request, door_id):
	door = get_object_or_404(Door, id=door_id)
	badge_number = request.POST.get("badge_number")
	if not badge_number:
		return render(request, "area_access/badge_not_found.html")
	try:
		user = User.objects.get(badge_number=badge_number)
	except User.DoesNotExist:
		return render(request, "area_access/badge_not_found.html")
	if user.area_access_record() and user.area_access_record().area == door.area:
		log = PhysicalAccessLog(
			user=user,
			door=door,
			time=timezone.now(),
			result=PhysicalAccessType.ALLOW,
			details="The user was permitted to enter this area, and already had an active area access record for this area.",
		)
		log.save()
		# If we cannot open the door, display message and let them try again or exit since there is nothing else to do (user is already logged in).
		if not door.interlock.unlock():
			return interlock_error(bypass_allowed=False)
		delay_lock_door(door.id)
		return render(request, "area_access/door_is_open.html")
	return render(request, "area_access/not_logged_in.html", {"area": door.area})


def interlock_error(action: str = None, user: User = None, bypass_allowed: bool = None):
	error_message = get_customization('door_interlock_failure_message')
	bypass_allowed = interlock_bypass_allowed(user) if bypass_allowed is None else bypass_allowed
	dictionary = {
		"message": linebreaksbr(error_message),
		"bypass_allowed": bypass_allowed,
		"action": action
	}
	return JsonResponse(dictionary, status=501)
