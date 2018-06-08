from datetime import timedelta, datetime
from http import HTTPStatus
from re import match

from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required, permission_required
from django.core.mail import send_mail
from django.db.models import Q
from django.http import HttpResponseBadRequest, HttpResponse, HttpResponseNotFound
from django.shortcuts import render, get_object_or_404, redirect
from django.template import Template, Context
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from NEMO.decorators import disable_session_expiry_refresh
from NEMO.models import Tool, Reservation, Configuration, UsageEvent, AreaAccessRecord, StaffCharge, User, Project, ScheduledOutage, ScheduledOutageCategory
from NEMO.utilities import bootstrap_primary_color, extract_times, extract_dates, format_datetime, parse_parameter_string
from NEMO.views.constants import ADDITIONAL_INFORMATION_MAXIMUM_LENGTH
from NEMO.views.customization import get_customization, get_media_file_contents
from NEMO.views.policy import check_policy_to_save_reservation, check_policy_to_cancel_reservation, check_policy_to_create_outage
from NEMO.widgets.tool_tree import ToolTree


@login_required
@require_GET
def calendar(request, tool_id=None):
	""" Present the calendar view to the user. """

	if request.device == 'mobile':
		if tool_id:
			return redirect('view_calendar', tool_id)
		else:
			return redirect('choose_tool', 'view_calendar')

	tools = Tool.objects.filter(visible=True).order_by('category', 'name')
	rendered_tool_tree_html = ToolTree().render(None, {'tools': tools})
	dictionary = {
		'rendered_tool_tree_html': rendered_tool_tree_html,
		'tools': tools,
		'auto_select_tool': tool_id,
	}
	if request.user.is_staff:
		dictionary['users'] = User.objects.all()
	return render(request, 'calendar/calendar.html', dictionary)


@login_required
@require_GET
@disable_session_expiry_refresh
def event_feed(request):
	""" Get all reservations for a specific time-window. Optionally: filter by tool or user name. """
	try:
		start, end = extract_dates(request.GET)
	except Exception as e:
		return HttpResponseBadRequest('Invalid start or end time. ' + str(e))

	# We don't want to let someone hammer the database with phony calendar feed lookups.
	# Block any requests that have a duration of more than 8 weeks. The FullCalendar
	# should only ever request 6 weeks of data at a time (at most).
	if end - start > timedelta(weeks=8):
		return HttpResponseBadRequest("Calendar feed request has too long a duration: " + str(end - start))

	event_type = request.GET.get('event_type')

	if event_type == 'reservations':
		return reservation_event_feed(request, start, end)
	elif event_type == 'nanofab usage':
		return usage_event_feed(request, start, end)
	# Only staff may request a specific user's history...
	elif event_type == 'specific user' and request.user.is_staff:
		user = get_object_or_404(User, id=request.GET.get('user'))
		return specific_user_feed(request, user, start, end)
	else:
		return HttpResponseBadRequest('Invalid event type or operation not authorized.')


def reservation_event_feed(request, start, end):
	events = Reservation.objects.filter(cancelled=False, missed=False, shortened=False)
	outages = None
	# Exclude events for which the following is true:
	# The event starts and ends before the time-window, and...
	# The event starts and ends after the time-window.
	events = events.exclude(start__lt=start, end__lt=start)
	events = events.exclude(start__gt=end, end__gt=end)

	# Filter events that only have to do with the relevant tool.
	tool = request.GET.get('tool_id')
	if tool:
		events = events.filter(tool__id=tool)

		outages = ScheduledOutage.objects.filter(Q(tool=tool) | Q(resource__fully_dependent_tools__in=[tool]))
		outages = outages.exclude(start__lt=start, end__lt=start)
		outages = outages.exclude(start__gt=end, end__gt=end)

	# Filter events that only have to do with the current user.
	personal_schedule = request.GET.get('personal_schedule')
	if personal_schedule:
		events = events.filter(user=request.user)

	dictionary = {
		'events': events,
		'outages': outages,
		'personal_schedule': personal_schedule,
	}
	return render(request, 'calendar/reservation_event_feed.html', dictionary)


def usage_event_feed(request, start, end):
	usage_events = UsageEvent.objects
	# Exclude events for which the following is true:
	# The event starts and ends before the time-window, and...
	# The event starts and ends after the time-window.
	usage_events = usage_events.exclude(start__lt=start, end__lt=start)
	usage_events = usage_events.exclude(start__gt=end, end__gt=end)

	# Filter events that only have to do with the relevant tool.
	tool = request.GET.get('tool_id')
	if tool:
		usage_events = usage_events.filter(tool__id=tool)

	area_access_events = None
	# Filter events that only have to do with the current user.
	personal_schedule = request.GET.get('personal_schedule')
	if personal_schedule:
		usage_events = usage_events.filter(user=request.user)
		# Display area access along side tool usage when 'personal schedule' is selected.
		area_access_events = AreaAccessRecord.objects.filter(customer__id=request.user.id)
		area_access_events = area_access_events.exclude(start__lt=start, end__lt=start)
		area_access_events = area_access_events.exclude(start__gt=end, end__gt=end)

	missed_reservations = None
	if personal_schedule:
		missed_reservations = Reservation.objects.filter(missed=True, user=request.user)
	elif tool:
		missed_reservations = Reservation.objects.filter(missed=True, tool=tool)
	if missed_reservations:
		missed_reservations = missed_reservations.exclude(start__lt=start, end__lt=start)
		missed_reservations = missed_reservations.exclude(start__gt=end, end__gt=end)

	dictionary = {
		'usage_events': usage_events,
		'area_access_events': area_access_events,
		'personal_schedule': personal_schedule,
		'missed_reservations': missed_reservations,
	}
	return render(request, 'calendar/usage_event_feed.html', dictionary)


def specific_user_feed(request, user, start, end):
	# Find all tool usage events for a user.
	# Exclude events for which the following is true:
	# The event starts and ends before the time-window, and...
	# The event starts and ends after the time-window.
	usage_events = UsageEvent.objects.filter(user=user)
	usage_events = usage_events.exclude(start__lt=start, end__lt=start)
	usage_events = usage_events.exclude(start__gt=end, end__gt=end)

	# Find all area access events for a user.
	area_access_events = AreaAccessRecord.objects.filter(customer=user)
	area_access_events = area_access_events.exclude(start__lt=start, end__lt=start)
	area_access_events = area_access_events.exclude(start__gt=end, end__gt=end)

	# Find all reservations for the user that were not missed or cancelled.
	reservations = Reservation.objects.filter(user=user, missed=False, cancelled=False, shortened=False)
	reservations = reservations.exclude(start__lt=start, end__lt=start)
	reservations = reservations.exclude(start__gt=end, end__gt=end)

	# Find all missed reservations for the user.
	missed_reservations = Reservation.objects.filter(user=user, missed=True)
	missed_reservations = missed_reservations.exclude(start__lt=start, end__lt=start)
	missed_reservations = missed_reservations.exclude(start__gt=end, end__gt=end)

	dictionary = {
		'usage_events': usage_events,
		'area_access_events': area_access_events,
		'reservations': reservations,
		'missed_reservations': missed_reservations,
	}
	return render(request, 'calendar/specific_user_feed.html', dictionary)


@login_required
@require_POST
def create_reservation(request):
	""" Create a reservation for a user. """
	try:
		start, end = extract_times(request.POST)
	except Exception as e:
		return HttpResponseBadRequest(str(e))
	tool = get_object_or_404(Tool, name=request.POST.get('tool_name'))
	explicit_policy_override = False
	if request.user.is_staff:
		try:
			user = User.objects.get(id=request.POST['impersonate'])
		except:
			user = request.user
		try:
			explicit_policy_override = request.POST['explicit_policy_override'] == 'true'
		except:
			pass
	else:
		user = request.user
	# Create the new reservation:
	new_reservation = Reservation()
	new_reservation.user = user
	new_reservation.creator = request.user
	new_reservation.tool = tool
	new_reservation.start = start
	new_reservation.end = end
	new_reservation.short_notice = determine_insufficient_notice(tool, start)
	policy_problems, overridable = check_policy_to_save_reservation(None, new_reservation, user, explicit_policy_override)

	# If there was a problem in saving the reservation then return the error...
	if policy_problems:
		return render(request, 'calendar/policy_dialog.html', {'policy_problems': policy_problems, 'overridable': overridable and request.user.is_staff})

	# All policy checks have passed.

	# If the user only has one project then associate it with the reservation.
	# Otherwise, present a dialog box for the user to choose which project to associate.
	active_projects = user.active_projects()
	if len(active_projects) == 1:
		new_reservation.project = active_projects[0]
	else:
		try:
			new_reservation.project = Project.objects.get(id=request.POST['project_id'])
		except:
			return render(request, 'calendar/project_choice.html', {'active_projects': active_projects})

	# Make sure the user is actually enrolled on the project. We wouldn't want someone
	# forging a request to reserve against a project they don't belong to.
	if new_reservation.project not in new_reservation.user.active_projects():
		return render(request, 'calendar/project_choice.html', {'active_projects': active_projects()})

	configured = (request.POST.get('configured') == "true")
	# If a reservation is requested and the tool does not require configuration...
	if not tool.is_configurable():
		new_reservation.save()
		return HttpResponse()

	# If a reservation is requested and the tool requires configuration that has not been submitted...
	elif tool.is_configurable() and not configured:
		configuration_information = tool.get_configuration_information(user=user, start=start)
		return render(request, 'calendar/configuration.html', configuration_information)

	# If a reservation is requested and configuration information is present also...
	elif tool.is_configurable() and configured:
		new_reservation.additional_information, new_reservation.self_configuration = extract_configuration(request)
		# Reservation can't be short notice if the user is configuring the tool themselves.
		if new_reservation.self_configuration:
			new_reservation.short_notice = False
		new_reservation.save()
		return HttpResponse()

	return HttpResponseBadRequest("Reservation creation failed because invalid parameters were sent to the server.")


def extract_configuration(request):
	cleaned_configuration = []
	for key, value in request.POST.items():
		entry = parse_configuration_entry(key, value)
		if entry:
			cleaned_configuration.append(entry)
	# Sort by configuration display priority and join the results:
	result = ''
	for config in sorted(cleaned_configuration):
		result += config[1] + '\n'
	if 'additional_information' in request.POST:
		result += request.POST['additional_information'][:ADDITIONAL_INFORMATION_MAXIMUM_LENGTH].strip()
	self_configuration = True if request.POST.get('self_configuration') == 'on' else False
	return result, self_configuration


def parse_configuration_entry(key, value):
	if value == "" or not match("^configuration_[0-9]+__slot_[0-9]+__display_priority_[0-9]+$", key):
		return None
	config_id, slot, display_priority = [int(s) for s in key.split('_') if s.isdigit()]
	configuration = Configuration.objects.get(pk=config_id)
	available_setting = configuration.get_available_setting(value)
	if len(configuration.current_settings_as_list()) == 1:
		return display_priority, configuration.name + " needs to be set to " + available_setting + "."
	else:
		return display_priority, configuration.configurable_item_name + " #" + str(slot + 1) + " needs to be set to " + available_setting + "."


@staff_member_required(login_url=None)
@require_POST
def create_outage(request):
	""" Create a reservation for a user. """
	try:
		start, end = extract_times(request.POST)
	except Exception as e:
		return HttpResponseBadRequest(str(e))
	tool = get_object_or_404(Tool, name=request.POST.get('tool_name'))
	# Create the new reservation:
	outage = ScheduledOutage()
	outage.creator = request.user
	outage.category = request.POST.get('category', '')[:200]
	outage.tool = tool
	outage.start = start
	outage.end = end

	# If there was a problem in saving the reservation then return the error...
	policy_problem = check_policy_to_create_outage(outage)
	if policy_problem:
		return HttpResponseBadRequest(policy_problem)

	# Make sure there is at least an outage title
	if not request.POST.get('title'):
		dictionary = {'categories': ScheduledOutageCategory.objects.all()}
		return render(request, 'calendar/scheduled_outage_information.html', dictionary)

	outage.title = request.POST['title']
	outage.details = request.POST.get('details', '')

	outage.save()
	return HttpResponse()


@login_required
@require_POST
def resize_reservation(request):
	""" Resize a reservation for a user. """
	try:
		delta = timedelta(minutes=int(request.POST['delta']))
	except:
		return HttpResponseBadRequest('Invalid delta')
	return modify_reservation(request, None, delta)


@staff_member_required(login_url=None)
@require_POST
def resize_outage(request):
	""" Resize an outage """
	try:
		delta = timedelta(minutes=int(request.POST['delta']))
	except:
		return HttpResponseBadRequest('Invalid delta')
	return modify_outage(request, None, delta)


@login_required
@require_POST
def move_reservation(request):
	""" Move a reservation for a user. """
	try:
		delta = timedelta(minutes=int(request.POST['delta']))
	except:
		return HttpResponseBadRequest('Invalid delta')
	return modify_reservation(request, delta, delta)


@staff_member_required(login_url=None)
@require_POST
def move_outage(request):
	""" Move a reservation for a user. """
	try:
		delta = timedelta(minutes=int(request.POST['delta']))
	except:
		return HttpResponseBadRequest('Invalid delta')
	return modify_outage(request, delta, delta)


def modify_reservation(request, start_delta, end_delta):
	"""
	Cancel the user's old reservation and create a new one. Reservations are cancelled and recreated so that
	reservation abuse can be tracked if necessary. This function should be called by other views and should
	not be tied directly to a URL.
	"""
	try:
		reservation_to_cancel = Reservation.objects.get(pk=request.POST['id'])
	except Reservation.DoesNotExist:
		return HttpResponseNotFound("The reservation that you wish to modify doesn't exist!")
	response = check_policy_to_cancel_reservation(reservation_to_cancel, request.user)
	# Do not move the reservation if the user was not authorized to cancel it.
	if response.status_code != HTTPStatus.OK:
		return response
	# Record the current time so that the timestamp of the cancelled reservation and the new reservation match exactly.
	now = timezone.now()
	# Cancel the user's original reservation.
	reservation_to_cancel.cancelled = True
	reservation_to_cancel.cancellation_time = now
	reservation_to_cancel.cancelled_by = request.user
	# Create a new reservation for the user.
	new_reservation = Reservation()
	new_reservation.title = reservation_to_cancel.title
	new_reservation.creator = request.user
	new_reservation.additional_information = reservation_to_cancel.additional_information
	# A change in start time will only be provided if the reservation is being moved.
	new_reservation.start = reservation_to_cancel.start
	new_reservation.self_configuration = reservation_to_cancel.self_configuration
	new_reservation.short_notice = False
	if start_delta:
		new_reservation.start += start_delta
	if new_reservation.self_configuration:
		# Reservation can't be short notice since the user is configuring the tool themselves.
		new_reservation.short_notice = False
	else:
		new_reservation.short_notice = determine_insufficient_notice(reservation_to_cancel.tool, new_reservation.start)
	# A change in end time will always be provided for reservation move and resize operations.
	new_reservation.end = reservation_to_cancel.end + end_delta
	new_reservation.tool = reservation_to_cancel.tool
	new_reservation.project = reservation_to_cancel.project
	new_reservation.user = reservation_to_cancel.user
	new_reservation.creation_time = now
	policy_problems, overridable = check_policy_to_save_reservation(reservation_to_cancel, new_reservation, request.user, False)
	if policy_problems:
		return HttpResponseBadRequest(policy_problems[0])
	else:
		# All policy checks passed, so save the reservation.
		new_reservation.save()
		reservation_to_cancel.descendant = new_reservation
		reservation_to_cancel.save()
	return response


def modify_outage(request, start_delta, end_delta):
	try:
		outage = ScheduledOutage.objects.get(pk=request.POST['id'])
	except ScheduledOutage.DoesNotExist:
		return HttpResponseNotFound("The outage that you wish to modify doesn't exist!")
	if start_delta:
		outage.start += start_delta
	outage.end += end_delta
	policy_problem = check_policy_to_create_outage(outage)
	if policy_problem:
		return HttpResponseBadRequest(policy_problem)
	else:
		# All policy checks passed, so save the reservation.
		outage.save()
	return HttpResponse()


def determine_insufficient_notice(tool, start):
	""" Determines if a reservation is created that does not give the
	NanoFab staff sufficient advance notice to configure a tool. """
	for config in tool.configuration_set.all():
		advance_notice = start - timezone.now()
		if advance_notice < timedelta(hours=config.advance_notice_limit):
			return True
	return False


@login_required
@require_POST
def cancel_reservation(request, reservation_id):
	""" Cancel a reservation for a user. """
	reservation = get_object_or_404(Reservation, id=reservation_id)
	response = check_policy_to_cancel_reservation(reservation, request.user)
	# Staff must provide a reason when cancelling a reservation they do not own.
	reason = parse_parameter_string(request.POST, 'reason')
	if reservation.user != request.user and not reason:
		response = HttpResponseBadRequest("You must provide a reason when cancelling someone else's reservation.")

	if response.status_code == HTTPStatus.OK:
		# All policy checks passed, so cancel the reservation.
		reservation.cancelled = True
		reservation.cancellation_time = timezone.now()
		reservation.cancelled_by = request.user
		reservation.save()

		if reason:
			dictionary = {
				'staff_member': request.user,
				'reservation': reservation,
				'reason': reason,
				'template_color': bootstrap_primary_color('info')
			}
			email_contents = get_media_file_contents('cancellation_email.html')
			if email_contents:
				cancellation_email = Template(email_contents).render(Context(dictionary))
				reservation.user.email_user('Your reservation was cancelled', cancellation_email, request.user.email)

	if request.device == 'desktop':
		return response
	if request.device == 'mobile':
		if response.status_code == HTTPStatus.OK:
			return render(request, 'mobile/cancellation_result.html', {'event_type': 'Reservation', 'tool': reservation.tool})
		else:
			return render(request, 'mobile/error.html', {'message': response.content})


@staff_member_required(login_url=None)
@require_POST
def cancel_outage(request, outage_id):
	outage = get_object_or_404(ScheduledOutage, id=outage_id)
	outage.delete()
	if request.device == 'desktop':
		return HttpResponse()
	if request.device == 'mobile':
		dictionary = {'event_type': 'Scheduled outage', 'tool': outage.tool}
		return render(request, 'mobile/cancellation_result.html', dictionary)


@staff_member_required(login_url=None)
@require_POST
def set_reservation_title(request, reservation_id):
	""" Cancel a reservation for a user. """
	reservation = get_object_or_404(Reservation, id=reservation_id)
	reservation.title = request.POST.get('title', '')[:reservation._meta.get_field('title').max_length]
	reservation.save()
	return HttpResponse()


@login_required
@permission_required('NEMO.trigger_timed_services', raise_exception=True)
@require_GET
def email_reservation_reminders(request):
	# Exit early if the reservation reminder email template has not been customized for the organization yet.
	reservation_reminder_message = get_media_file_contents('reservation_reminder_email.html')
	reservation_warning_message = get_media_file_contents('reservation_warning_email.html')
	if not reservation_reminder_message or not reservation_warning_message:
		return HttpResponseNotFound('The reservation reminder email template has not been customized for your organization yet. Please visit the NEMO customizable_key_values page to upload a template, then reservation reminder email notifications can be sent.')

	# Find all reservations that are two hours from now, plus or minus 5 minutes to allow for time skew.
	preparation_time = 120
	tolerance = 5
	earliest_start = timezone.now() + timedelta(minutes=preparation_time) - timedelta(minutes=tolerance)
	latest_start = timezone.now() + timedelta(minutes=preparation_time) + timedelta(minutes=tolerance)
	upcoming_reservations = Reservation.objects.filter(cancelled=False, start__gt=earliest_start, start__lt=latest_start)
	# Email a reminder to each user with an upcoming reservation.
	for reservation in upcoming_reservations:
		tool = reservation.tool
		if tool.operational and not tool.problematic() and tool.all_resources_available():
			subject = reservation.tool.name + " reservation reminder"
			rendered_message = Template(reservation_reminder_message).render(Context({'reservation': reservation, 'template_color': bootstrap_primary_color('success')}))
		elif not tool.operational or tool.required_resource_is_unavailable():
			subject = reservation.tool.name + " reservation problem"
			rendered_message = Template(reservation_warning_message).render(Context({'reservation': reservation, 'template_color': bootstrap_primary_color('danger'), 'fatal_error': True}))
		else:
			subject = reservation.tool.name + " reservation warning"
			rendered_message = Template(reservation_warning_message).render(Context({'reservation': reservation, 'template_color': bootstrap_primary_color('warning'), 'fatal_error': False}))
		user_office_email = get_customization('user_office_email_address')
		reservation.user.email_user(subject, rendered_message, user_office_email)
	return HttpResponse()


@login_required
@permission_required('NEMO.trigger_timed_services', raise_exception=True)
@require_GET
def email_usage_reminders(request):
	projects_to_exclude = request.GET.getlist("projects_to_exclude[]")
	busy_users = AreaAccessRecord.objects.filter(end=None, staff_charge=None).exclude(project__id__in=projects_to_exclude)
	busy_tools = UsageEvent.objects.filter(end=None).exclude(project__id__in=projects_to_exclude)

	# Make lists of all the things a user is logged in to.
	# We don't want to send 3 separate emails if a user is logged into three things.
	# Just send one email for all the things!
	aggregate = {}
	for access_record in busy_users:
		key = str(access_record.customer)
		aggregate[key] = {
			'email': access_record.customer.email,
			'first_name': access_record.customer.first_name,
			'resources_in_use': [str(access_record.area)],
		}
	for usage_event in busy_tools:
		key = str(usage_event.operator)
		if key in aggregate:
			aggregate[key]['resources_in_use'].append(usage_event.tool.name)
		else:
			aggregate[key] = {
				'email': usage_event.operator.email,
				'first_name': usage_event.operator.first_name,
				'resources_in_use': [usage_event.tool.name],
			}

	user_office_email = get_customization('user_office_email_address')

	message = get_media_file_contents('usage_reminder_email.html')
	if message:
		subject = "NanoFab usage"
		for user in aggregate.values():
			rendered_message = Template(message).render(Context({'user': user}))
			send_mail(subject, '', user_office_email, [user['email']], html_message=rendered_message)

	message = get_media_file_contents('staff_charge_reminder_email.html')
	if message:
		busy_staff = StaffCharge.objects.filter(end=None)
		for staff_charge in busy_staff:
			subject = "Active staff charge since " + format_datetime(staff_charge.start)
			rendered_message = Template(message).render(Context({'staff_charge': staff_charge}))
			staff_charge.staff_member.email_user(subject, rendered_message, user_office_email)

	return HttpResponse()


@login_required
@require_GET
def reservation_details(request, reservation_id):
	reservation = get_object_or_404(Reservation, id=reservation_id)
	if reservation.cancelled:
		error_message = 'This reservation was cancelled by {0} at {1}.'.format(reservation.cancelled_by, format_datetime(reservation.cancellation_time))
		return HttpResponseNotFound(error_message)
	return render(request, 'calendar/reservation_details.html', {'reservation': reservation})


@login_required
@require_GET
def outage_details(request, outage_id):
	outage = get_object_or_404(ScheduledOutage, id=outage_id)
	return render(request, 'calendar/outage_details.html', {'outage': outage})


@login_required
@require_GET
def usage_details(request, event_id):
	event = get_object_or_404(UsageEvent, id=event_id)
	return render(request, 'calendar/usage_details.html', {'event': event})


@login_required
@require_GET
def area_access_details(request, event_id):
	event = get_object_or_404(AreaAccessRecord, id=event_id)
	return render(request, 'calendar/area_access_details.html', {'event': event})


@login_required
@require_GET
@permission_required('NEMO.trigger_timed_services', raise_exception=True)
def cancel_unused_reservations(request):
	# Exit early if the missed reservation email template has not been customized for the organization yet.
	if not get_media_file_contents('missed_reservation_email.html'):
		return HttpResponseNotFound('The missed reservation email template has not been customized for your organization yet. Please visit the NEMO customizable_key_values page to upload a template, then missed email notifications can be sent.')

	tools = Tool.objects.filter(visible=True, operational=True, missed_reservation_threshold__isnull=False)
	missed_reservations = []
	for tool in tools:
		# If a tool is in use then there's no need to look for unused reservation time.
		if tool.in_use() or tool.required_resource_is_unavailable() or tool.scheduled_outage_in_progress():
			continue
		# Calculate the timestamp of how long a user can be late for a reservation.
		threshold = (timezone.now() - timedelta(minutes=tool.missed_reservation_threshold))
		threshold = datetime.replace(threshold, second=0, microsecond=0)  # Round down to the nearest minute.
		# Find the reservations that began exactly at the threshold.
		reservation = Reservation.objects.filter(cancelled=False, missed=False, shortened=False, tool=tool, user__is_staff=False, start=threshold, end__gt=timezone.now())
		for r in reservation:
			# Staff may abandon reservations.
			if r.user.is_staff:
				continue
			# If there was no tool enable or disable event since the threshold timestamp then we assume the reservation has been missed.
			if not (UsageEvent.objects.filter(tool=tool, start__gte=threshold).exists() or UsageEvent.objects.filter(tool=tool, end__gte=threshold).exists()):
				# Mark the reservation as missed and notify the user & NanoFab staff.
				r.missed = True
				r.save()
				missed_reservations.append(r)

	for r in missed_reservations:
		send_missed_reservation_notification(r)

	return HttpResponse()


@staff_member_required(login_url=None)
@require_GET
def proxy_reservation(request):
	return render(request, 'calendar/proxy_reservation.html', {'users': User.objects.filter(is_active=True)})


def send_missed_reservation_notification(reservation):
	subject = "Missed reservation for the " + str(reservation.tool)
	message = get_media_file_contents('missed_reservation_email.html')
	message = Template(message).render(Context({'reservation': reservation}))
	user_office_email = get_customization('user_office_email_address')
	abuse_email = get_customization('abuse_email_address')
	send_mail(subject, '', user_office_email, [reservation.user.email, abuse_email, user_office_email], html_message=message)
