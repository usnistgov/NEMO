from datetime import timedelta

from django.core.mail import send_mail
from django.db.models import Q
from django.http import HttpResponse, HttpResponseBadRequest
from django.template import Template, Context
from django.utils import timezone

from NEMO.models import Reservation, AreaAccessRecord, ScheduledOutage
from NEMO.utilities import format_datetime
from NEMO.views.customization import get_customization, get_media_file_contents


def check_policy_to_enable_tool(tool, operator, user, project, staff_charge):
	"""
	Check that the user is allowed to enable the tool. Enable the tool if the policy checks pass.
	"""

	# The tool must be visible to users.
	if not tool.visible:
		return HttpResponseBadRequest("This tool is currently hidden from users.")

	# The tool must be operational.
	# If the tool is non-operational then it may only be accessed by staff members.
	if not tool.operational and not operator.is_staff:
		return HttpResponseBadRequest("This tool is currently non-operational.")

	# The tool must not be in use.
	current_usage_event = tool.get_current_usage_event()
	if current_usage_event:
		return HttpResponseBadRequest("The tool is currently being used by " + str(current_usage_event.user) + ".")

	# The user must be qualified to use the tool.
	if tool not in operator.qualifications.all() and not operator.is_staff:
		return HttpResponseBadRequest("You are not qualified to use this tool.")

	# Only staff members can operate a tool on behalf of another user.
	if (user and operator.pk != user.pk) and not operator.is_staff:
		return HttpResponseBadRequest("You must be a staff member to use a tool on another user's behalf.")

	# All required resources must be available to operate a tool except for staff.
	if tool.required_resource_set.filter(available=False).exists() and not operator.is_staff:
		return HttpResponseBadRequest("A resource that is required to operate this tool is unavailable.")

	# The tool operator may not activate tools in a particular area unless they are logged in to the area.
	# Staff are exempt from this rule.
	if tool.requires_area_access and AreaAccessRecord.objects.filter(area=tool.requires_area_access, customer=operator, staff_charge=None, end=None).count() == 0 and not operator.is_staff:
		dictionary = {
			'operator': operator,
			'tool': tool,
		}
		abuse_email_address = get_customization('abuse_email_address')
		message = get_media_file_contents('unauthorized_tool_access_email.html')
		if abuse_email_address and message:
			rendered_message = Template(message).render(Context(dictionary))
			send_mail("Area access requirement", '', abuse_email_address, [abuse_email_address], html_message=rendered_message)
		return HttpResponseBadRequest("You must be logged in to the {} to operate this tool.".format(tool.requires_area_access.name.lower()))

	# Staff may only charge staff time for one user at a time.
	if staff_charge and operator.charging_staff_time():
		return HttpResponseBadRequest('You are already charging staff time. You must end the current staff charge before you being another.')

	# Staff may not bill staff time to the themselves.
	if staff_charge and operator == user:
		return HttpResponseBadRequest('You cannot charge staff time to yourself.')

	# Users may only charge to projects they are members of.
	if project not in user.active_projects():
		return HttpResponseBadRequest('The designated user is not assigned to the selected project.')

	# The tool operator must not have a lock on usage
	if operator.training_required:
		return HttpResponseBadRequest("You are blocked from using all tools in the NanoFab. Please complete the NanoFab rules tutorial in order to use tools.")

	# Users may only use a tool when delayed logoff is not in effect. Staff are exempt from this rule.
	if tool.delayed_logoff_in_progress() and not operator.is_staff:
		return HttpResponseBadRequest("Delayed tool logoff is in effect. You must wait for the delayed logoff to expire before you can use the tool.")

	# Users may not enable a tool during a scheduled outage. Staff are exempt from this rule.
	if tool.scheduled_outage_in_progress() and not operator.is_staff:
		return HttpResponseBadRequest("A scheduled outage is in effect. You must wait for the outage to end before you can use the tool.")

	return HttpResponse()


def check_policy_to_disable_tool(tool, operator, downtime):
	""" Check that the user is allowed to disable the tool. """
	current_usage_event = tool.get_current_usage_event()
	if current_usage_event.operator != operator and current_usage_event.user != operator and not operator.is_staff:
		return HttpResponseBadRequest('You may not disable a tool while another user is using it unless you are a staff member.')
	if downtime < timedelta():
		return HttpResponseBadRequest('Downtime cannot be negative.')
	if downtime > timedelta(minutes=120):
		return HttpResponseBadRequest('Post-usage tool downtime may not exceed 120 minutes.')
	if tool.delayed_logoff_in_progress() and downtime > timedelta():
		return HttpResponseBadRequest('The tool is already in a delayed-logoff state. You may not issue additional delayed logoffs until the existing one expires.')
	if not tool.allow_delayed_logoff and downtime > timedelta():
		return HttpResponseBadRequest('Delayed logoff is not allowed for this tool.')
	return HttpResponse()


def check_policy_to_save_reservation(cancelled_reservation, new_reservation, user, explicit_policy_override):
	""" Check the reservation creation policy and return a list of policy problems """

	# The function will check all policies. Policy problems are placed in the policy_problems list. overridable is True if the policy problems can be overridden by a staff member.
	policy_problems = []
	overridable = False

	# Reservations may not have a start time that is earlier than the end time.
	if new_reservation.start >= new_reservation.end:
		policy_problems.append("Reservation start time (" + format_datetime(new_reservation.start) + ") must be before the end time (" + format_datetime(new_reservation.end) + ").")

	# The user may not create, move, or resize a reservation to coincide with another user's reservation.
	coincident_events = Reservation.objects.filter(tool=new_reservation.tool, cancelled=False, missed=False, shortened=False)
	# Exclude the reservation we're cancelling in order to create a new one:
	if cancelled_reservation and cancelled_reservation.id:
		coincident_events = coincident_events.exclude(id=cancelled_reservation.id)
	# Exclude events for which the following is true:
	# The event starts and ends before the time-window, and...
	# The event starts and ends after the time-window.
	coincident_events = coincident_events.exclude(start__lt=new_reservation.start, end__lte=new_reservation.start)
	coincident_events = coincident_events.exclude(start__gte=new_reservation.end, end__gt=new_reservation.end)
	if coincident_events.count() > 0:
		policy_problems.append("Your reservation coincides with another reservation that already exists. Please choose a different time.")

	# The user may not create, move, or resize a reservation to coincide with a scheduled outage.
	coincident_events = ScheduledOutage.objects.filter(Q(tool=new_reservation.tool) | Q(resource__fully_dependent_tools__in=[new_reservation.tool]))
	# Exclude events for which the following is true:
	# The event starts and ends before the time-window, and...
	# The event starts and ends after the time-window.
	coincident_events = coincident_events.exclude(start__lt=new_reservation.start, end__lte=new_reservation.start)
	coincident_events = coincident_events.exclude(start__gte=new_reservation.end, end__gt=new_reservation.end)
	if coincident_events.count() > 0:
		policy_problems.append("Your reservation coincides with a scheduled outage. Please choose a different time.")

	# Reservations that have been cancelled may not be changed.
	if new_reservation.cancelled:
		policy_problems.append("This reservation has already been cancelled by " + str(new_reservation.cancelled_by) + " at " + format_datetime(new_reservation.cancellation_time) + ".")

	# The user must belong to at least one active project to make a reservation.
	if new_reservation.user.active_project_count() < 1:
		if new_reservation.user == user:
			policy_problems.append("You do not belong to any active projects. Thus, you may not create any reservations.")
		else:
			policy_problems.append(str(new_reservation.user) + " does not belong to any active projects and cannot have reservations.")

	# The user must associate their reservation with a project they belong to.
	if new_reservation.project and new_reservation.project not in new_reservation.user.active_projects():
		if new_reservation.user == user:
			policy_problems.append("You do not belong to the project associated with this reservation.")
		else:
			policy_problems.append(str(new_reservation.user) + " does not belong to the project named " + str(new_reservation.project) + ".")

	# If the user is a staff member or there's an explicit policy override then the policy check is finished.
	if user.is_staff or explicit_policy_override:
		return policy_problems, overridable

	# If there are no blocking policy conflicts at this point, the rest of the policies can be overridden.
	if not policy_problems:
		overridable = True

	# The user must complete NEMO training to create reservations.
	# Staff may break this rule.
	# An explicit policy override allows this rule to be broken.
	if user.training_required:
		policy_problems.append("You are blocked from making reservations for all tools in the NanoFab. Please complete the NanoFab rules tutorial in order to create new reservations.")

	# Users may only change their own reservations.
	# Staff may break this rule.
	# An explicit policy override allows this rule to be broken.
	if new_reservation.user != user:
		policy_problems.append("You may not change reservations that you do not own.")

	# The user may not create or move a reservation to have a start time that is earlier than the current time.
	# Staff may break this rule.
	# An explicit policy override allows this rule to be broken.
	if new_reservation.start < timezone.now():
		policy_problems.append("Reservation start time (" + format_datetime(new_reservation.start) + ") is earlier than the current time (" + format_datetime(timezone.now()) + ").")

	# The user may not move or resize a reservation to have an end time that is earlier than the current time.
	# Staff may break this rule.
	# An explicit policy override allows this rule to be broken.
	if new_reservation.end < timezone.now():
		policy_problems.append("Reservation end time (" + format_datetime(new_reservation.end) + ") is earlier than the current time (" + format_datetime(timezone.now()) + ").")

	# The user must be qualified on the tool in question in order to create, move, or resize a reservation.
	# Staff may break this rule.
	# An explicit policy override allows this rule to be broken.
	if new_reservation.tool not in user.qualifications.all():
		policy_problems.append("You are not qualified to use this tool. Creating, moving, and resizing reservations is forbidden.")

	# The reservation start time may not exceed the tool's reservation horizon.
	# Staff may break this rule.
	# An explicit policy override allows this rule to be broken.
	if new_reservation.tool.reservation_horizon is not None:
		reservation_horizon = timedelta(days=new_reservation.tool.reservation_horizon)
		if new_reservation.start > timezone.now() + reservation_horizon:
			policy_problems.append("You may not create reservations further than " + str(reservation_horizon.days) + " days from now for this tool.")

	# Calculate the duration of the reservation:
	duration = new_reservation.end - new_reservation.start

	# The reservation must be at least as long as the minimum block time for this tool.
	# Staff may break this rule.
	# An explicit policy override allows this rule to be broken.
	if new_reservation.tool.minimum_usage_block_time:
		minimum_block_time = timedelta(minutes=new_reservation.tool.minimum_usage_block_time)
		if duration < minimum_block_time:
			policy_problems.append("Your reservation has a duration of " + str(int(duration.total_seconds() / 60)) + " minutes. This tool requires a minimum reservation duration of " + str(int(minimum_block_time.total_seconds() / 60)) + " minutes.")

	# The reservation may not exceed the maximum block time for this tool.
	# Staff may break this rule.
	# An explicit policy override allows this rule to be broken.
	if new_reservation.tool.maximum_usage_block_time:
		maximum_block_time = timedelta(minutes=new_reservation.tool.maximum_usage_block_time)
		if duration > maximum_block_time:
			policy_problems.append("Your reservation has a duration of " + str(int(duration.total_seconds() / 60)) + " minutes. Reservations for this tool may not exceed " + str(int(maximum_block_time.total_seconds() / 60)) + " minutes.")

	# If there is a limit on number of reservations per user per day then verify that the user has not exceeded it.
	# Staff may break this rule.
	# An explicit policy override allows this rule to be broken.
	if new_reservation.tool.maximum_reservations_per_day:
		start_of_day = new_reservation.start
		start_of_day = start_of_day.replace(hour=0, minute=0, second=0, microsecond=0)
		end_of_day = start_of_day + timedelta(days=1)
		reservations_for_that_day = Reservation.objects.filter(cancelled=False, shortened=False, start__gte=start_of_day, end__lte=end_of_day, user=user, tool=new_reservation.tool)
		# Exclude any reservation that is being cancelled.
		if cancelled_reservation and cancelled_reservation.id:
			reservations_for_that_day = reservations_for_that_day.exclude(id=cancelled_reservation.id)
		if reservations_for_that_day.count() >= new_reservation.tool.maximum_reservations_per_day:
			policy_problems.append("You may only have " + str(new_reservation.tool.maximum_reservations_per_day) + " reservations for this tool per day. Missed reservations are included when counting the number of reservations per day.")

	# A minimum amount of time between reservations for the same user & same tool can be enforced.
	# Staff may break this rule.
	# An explicit policy override allows this rule to be broken.
	if new_reservation.tool.minimum_time_between_reservations:
		buffer_time = timedelta(minutes=new_reservation.tool.minimum_time_between_reservations)
		must_end_before = new_reservation.start - buffer_time
		too_close = Reservation.objects.filter(cancelled=False, shortened=False, user=user, end__gt=must_end_before, start__lt=new_reservation.start, tool=new_reservation.tool)
		if cancelled_reservation and cancelled_reservation.id:
			too_close = too_close.exclude(id=cancelled_reservation.id)
		if too_close.exists():
			policy_problems.append("Separate reservations for this tool that belong to you must be at least " + str(new_reservation.tool.minimum_time_between_reservations) + " minutes apart from each other. The proposed reservation ends too close to another reservation.")
		must_start_after = new_reservation.end + buffer_time
		too_close = Reservation.objects.filter(cancelled=False, shortened=False, user=user, start__lt=must_start_after, end__gt=new_reservation.start, tool=new_reservation.tool)
		if cancelled_reservation and cancelled_reservation.id:
			too_close = too_close.exclude(id=cancelled_reservation.id)
		if too_close.exists():
			policy_problems.append("Separate reservations for this tool that belong to you must be at least " + str(new_reservation.tool.minimum_time_between_reservations) + " minutes apart from each other. The proposed reservation begins too close to another reservation.")

	# Check that the user is not exceeding the maximum amount of time they may reserve in the future.
	# Staff may break this rule.
	# An explicit policy override allows this rule to be broken.
	if new_reservation.tool.maximum_future_reservation_time:
		reservations_after_now = Reservation.objects.filter(cancelled=False, user=user, tool=new_reservation.tool, start__gte=timezone.now())
		if cancelled_reservation and cancelled_reservation.id:
			reservations_after_now = reservations_after_now.exclude(id=cancelled_reservation.id)
		amount_reserved_in_the_future = new_reservation.duration()
		for r in reservations_after_now:
			amount_reserved_in_the_future += r.duration()
		if amount_reserved_in_the_future.total_seconds() / 60 > new_reservation.tool.maximum_future_reservation_time:
			policy_problems.append("You may only reserve up to " + str(new_reservation.tool.maximum_future_reservation_time) + " minutes of time on this tool, starting from the current time onward.")

	# Return the list of all policies that are not met.
	return policy_problems, overridable


def check_policy_to_cancel_reservation(reservation, user):
	"""
	Checks the reservation deletion policy.
	If all checks pass the function returns an HTTP "OK" response.
	Otherwise, the function returns an HTTP "Bad Request" with an error message.
	"""

	# Users may only cancel reservations that they own.
	# Staff may break this rule.
	if (reservation.user != user) and not user.is_staff:
		return HttpResponseBadRequest("You may not cancel reservations that you do not own.")

	# Users may not cancel reservations that have already ended.
	# Staff may break this rule.
	if reservation.end < timezone.now() and not user.is_staff:
		return HttpResponseBadRequest("You may not cancel reservations that have already ended.")

	if reservation.cancelled:
		return HttpResponseBadRequest("This reservation has already been cancelled by " + str(reservation.cancelled_by) + " at " + format_datetime(reservation.cancellation_time) + ".")

	if reservation.missed:
		return HttpResponseBadRequest("This reservation was missed and cannot be modified.")

	return HttpResponse()


def check_policy_to_create_outage(outage):
	policy_problems = []
	# Outages may not have a start time that is earlier than the end time.
	if outage.start >= outage.end:
		return "Outage start time (" + format_datetime(outage.start) + ") must be before the end time (" + format_datetime(outage.end) + ")."

	# The user may not create, move, or resize an outage to coincide with another user's reservation.
	coincident_events = Reservation.objects.filter(tool=outage.tool, cancelled=False, missed=False, shortened=False)
	# Exclude events for which the following is true:
	# The event starts and ends before the time-window, and...
	# The event starts and ends after the time-window.
	coincident_events = coincident_events.exclude(start__lt=outage.start, end__lte=outage.start)
	coincident_events = coincident_events.exclude(start__gte=outage.end, end__gt=outage.end)
	if coincident_events.count() > 0:
		return "Your scheduled outage coincides with a reservation that already exists. Please choose a different time."

	# No policy issues! The outage can be created...
	return None
