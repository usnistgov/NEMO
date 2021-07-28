import io
from collections import Iterable
from copy import deepcopy
from datetime import timedelta, datetime
from http import HTTPStatus
from json import loads, dumps
from logging import getLogger
from re import match
from typing import List, Optional, Union

import pytz
from dateutil import rrule
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required, permission_required
from django.db.models import Q
from django.http import HttpResponseBadRequest, HttpResponse, HttpResponseNotFound
from django.shortcuts import render, get_object_or_404, redirect
from django.template import Template, Context
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from NEMO.decorators import disable_session_expiry_refresh
from NEMO.exceptions import ProjectChargeException, RequiredUnansweredQuestionsException
from NEMO.models import Tool, Reservation, Configuration, UsageEvent, AreaAccessRecord, StaffCharge, User, Project, ScheduledOutage, ScheduledOutageCategory, Area, ReservationItemType, ReservationQuestions
from NEMO.tasks import synchronized
from NEMO.utilities import bootstrap_primary_color, extract_times, extract_dates, format_datetime, parse_parameter_string, send_mail, create_email_attachment, localize, EmailCategory
from NEMO.views.constants import ADDITIONAL_INFORMATION_MAXIMUM_LENGTH
from NEMO.views.customization import get_customization, get_media_file_contents
from NEMO.views.policy import check_policy_to_save_reservation, check_policy_to_cancel_reservation, check_policy_to_create_outage, maximum_users_in_overlapping_reservations, check_tool_reservation_requiring_area, check_billing_to_project
from NEMO.widgets.dynamic_form import DynamicForm

calendar_logger = getLogger(__name__)

recurrence_frequency_display = {
	'DAILY': 'Day(s)',
	'DAILY_WEEKDAYS': 'Week Day(s)',
	'DAILY WEEKENDS': 'Weekend Day(s)',
	'WEEKLY': 'Week(s)',
	'MONTHLY': 'Month(s)',
}

recurrence_frequencies = {
	'DAILY': rrule.DAILY,
	'DAILY_WEEKDAYS': rrule.DAILY,
	'DAILY WEEKENDS': rrule.DAILY,
	'WEEKLY': rrule.WEEKLY,
	'MONTHLY': rrule.MONTHLY,
}


@login_required
@require_GET
def calendar(request, item_type=None, item_id=None):
	""" Present the calendar view to the user. """
	user:User = request.user
	if request.device == 'mobile':
		if item_type and item_type == 'tool' and item_id:
			return redirect('view_calendar', item_id)
		else:
			return redirect('choose_item', 'view_calendar')

	tools = Tool.objects.filter(visible=True).only('name', '_category', 'parent_tool_id').order_by('_category', 'name')
	areas = Area.objects.filter(requires_reservation=True).only('name')

	# We want to remove areas the user doesn't have access to
	display_all_areas = get_customization('calendar_display_not_qualified_areas') == 'enabled'
	if not display_all_areas and areas and user and not user.is_superuser:
		areas = [area for area in areas if area in user.accessible_areas()]

	from NEMO.widgets.item_tree import ItemTree
	rendered_item_tree_html = ItemTree().render(None, {'tools': tools, 'areas':areas, 'user': request.user})

	calendar_view = get_customization('calendar_view')
	calendar_first_day_of_week = get_customization('calendar_first_day_of_week')
	calendar_day_column_format = get_customization('calendar_day_column_format')
	calendar_week_column_format = get_customization('calendar_week_column_format')
	calendar_month_column_format = get_customization('calendar_month_column_format')
	calendar_start_of_the_day = get_customization('calendar_start_of_the_day')
	calendar_now_indicator = get_customization('calendar_now_indicator')
	calendar_all_tools = get_customization('calendar_all_tools')
	calendar_all_areas = get_customization('calendar_all_areas')
	calendar_all_areastools = get_customization('calendar_all_areastools')

	dictionary = {
		'rendered_item_tree_html': rendered_item_tree_html,
		'tools': list(tools),
		'areas': list(areas),
		'auto_select_item_id': item_id,
		'auto_select_item_type': item_type,
		'calendar_view' : calendar_view,
		'calendar_first_day_of_week' : calendar_first_day_of_week,
		'calendar_day_column_format' : calendar_day_column_format,
		'calendar_week_column_format' : calendar_week_column_format,
		'calendar_month_column_format' : calendar_month_column_format,
		'calendar_start_of_the_day' : calendar_start_of_the_day,
		'calendar_now_indicator' : calendar_now_indicator,
		'calendar_all_tools': calendar_all_tools,
		'calendar_all_areas': calendar_all_areas,
		'calendar_all_areastools': calendar_all_areastools,
		'self_login': False,
		'self_logout': False,
	}
	login_logout = get_customization('calendar_login_logout', False)
	self_login = get_customization('self_log_in', False)
	self_logout = get_customization('self_log_out', False)
	if login_logout == 'enabled':
		dictionary['self_login'] = self_login == 'enabled'
		dictionary['self_logout'] = self_logout == 'enabled'
	if request.user.is_staff:
		dictionary['users'] = User.objects.all()
	return render(request, 'calendar/calendar.html', dictionary)


@login_required
@require_GET
@disable_session_expiry_refresh
def event_feed(request):
	""" Get all reservations for a specific time-window. Optionally: filter by tool, area or user name. """
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

	facility_name = get_customization('facility_name')
	if event_type == 'reservations':
		return reservation_event_feed(request, start, end)
	elif event_type == f"{facility_name.lower()} usage":
		return usage_event_feed(request, start, end)
	# Only staff may request a specific user's history...
	elif event_type == 'specific user' and request.user.is_staff:
		user = get_object_or_404(User, id=request.GET.get('user'))
		return specific_user_feed(request, user, start, end)
	else:
		return HttpResponseBadRequest('Invalid event type or operation not authorized.')


def reservation_event_feed(request, start, end):
	events = Reservation.objects.filter(cancelled=False, missed=False, shortened=False)
	outages = ScheduledOutage.objects.none()
	# Exclude events for which the following is true:
	# The event starts and ends before the time-window, and...
	# The event starts and ends after the time-window.
	events = events.exclude(start__lt=start, end__lt=start)
	events = events.exclude(start__gt=end, end__gt=end)
	all_tools = request.GET.get('all_tools')
	all_areas = request.GET.get('all_areas')
	all_areastools = request.GET.get('all_areastools')

	# Filter events that only have to do with the relevant tool/area.
	item_type = request.GET.get('item_type')
	if all_tools:
		events = events.filter(area=None)
	elif all_areas:
		events = events.filter(tool=None)
	if item_type:
		item_type = ReservationItemType(item_type)
		item_id = request.GET.get('item_id')
		if item_id and not (all_tools or all_areas or all_areastools):
			events = events.filter(**{f'{item_type.value}__id': item_id})
			if item_type == ReservationItemType.TOOL:
				outages = ScheduledOutage.objects.filter(Q(tool=item_id) | Q(resource__fully_dependent_tools__in=[item_id]))
			elif item_type == ReservationItemType.AREA:
				outages = Area.objects.get(pk=item_id).scheduled_outage_queryset()

	# Exclude outages for which the following is true:
	# The outage starts and ends before the time-window, and...
	# The outage starts and ends after the time-window.
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
		'all_tools': all_tools,
		'all_areas': all_areas,
		'all_areastools': all_areastools,
	}
	return render(request, 'calendar/reservation_event_feed.html', dictionary)


def usage_event_feed(request, start, end):
	usage_events = UsageEvent.objects.none()
	area_access_events = AreaAccessRecord.objects.none()
	missed_reservations = Reservation.objects.none()

	item_id = request.GET.get('item_id')
	item_type = ReservationItemType(request.GET.get('item_type')) if request.GET.get('item_type') else None

	personal_schedule = request.GET.get('personal_schedule')
	all_areas = request.GET.get('all_areas')
	all_tools = request.GET.get('all_tools')
	all_areastools = request.GET.get('all_areastools')

	if personal_schedule:
		# Filter events that only have to do with the current user.
		# Display missed reservations, tool and area usage when 'personal schedule' is selected
		usage_events = UsageEvent.objects.filter(user=request.user)
		area_access_events = AreaAccessRecord.objects.filter(customer=request.user)
		missed_reservations = Reservation.objects.filter(missed=True, user=request.user)
	elif all_areas:
		area_access_events = AreaAccessRecord.objects.filter()
		missed_reservations = Reservation.objects.filter(missed=True, tool=None)
	elif all_tools:
		usage_events = UsageEvent.objects.filter()
		missed_reservations = Reservation.objects.filter(missed=True, area=None)
	elif all_areastools:
		usage_events = UsageEvent.objects.all()
		area_access_events = AreaAccessRecord.objects.filter()
		missed_reservations = Reservation.objects.filter(missed=True)
	elif item_type:
		reservation_filter = {item_type.value: item_id}
		missed_reservations = Reservation.objects.filter(missed=True).filter(**reservation_filter)
		# Filter events that only have to do with the relevant tool or area.
		if item_id and item_type == ReservationItemType.TOOL:
			usage_events = UsageEvent.objects.filter(tool__id__in=Tool.objects.get(pk=item_id).get_family_tool_ids())
		if item_id and item_type == ReservationItemType.AREA:
			area_access_events = AreaAccessRecord.objects.filter(area__id=item_id)

	# Exclude events for which the following is true:
	# The event starts and ends before the time-window, and...
	# The event starts and ends after the time-window.
	usage_events = usage_events.exclude(start__lt=start, end__lt=start)
	usage_events = usage_events.exclude(start__gt=end, end__gt=end)
	area_access_events = area_access_events.exclude(start__lt=start, end__lt=start)
	area_access_events = area_access_events.exclude(start__gt=end, end__gt=end)
	missed_reservations = missed_reservations.exclude(start__lt=start, end__lt=start)
	missed_reservations = missed_reservations.exclude(start__gt=end, end__gt=end)

	dictionary = {
		'usage_events': usage_events,
		'area_access_events': area_access_events,
		'personal_schedule': personal_schedule,
		'missed_reservations': missed_reservations,
		'all_tools': all_tools,
		'all_areas': all_areas,
		'all_areastools': all_areastools,
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
		item_type = request.POST['item_type']
		item_id = request.POST.get('item_id')
	except Exception as e:
		return HttpResponseBadRequest(str(e))
	return create_item_reservation(request, request.user, start, end, ReservationItemType(item_type), item_id)


@synchronized("current_user")
def create_item_reservation(request, current_user, start, end, item_type: ReservationItemType, item_id):
	item = get_object_or_404(item_type.get_object_class(), id=item_id)
	explicit_policy_override = False
	if current_user.is_staff:
		try:
			user = User.objects.get(id=request.POST['impersonate'])
		except:
			user = current_user
		try:
			explicit_policy_override = request.POST['explicit_policy_override'] == 'true'
		except:
			pass
	else:
		user = current_user
	# Create the new reservation:
	new_reservation = Reservation()
	new_reservation.user = user
	new_reservation.creator = current_user
	# set tool or area
	setattr(new_reservation, item_type.value, item)
	new_reservation.start = start
	new_reservation.end = end
	new_reservation.short_notice = determine_insufficient_notice(item, start) if item_type == ReservationItemType.TOOL else False
	policy_problems, overridable = check_policy_to_save_reservation(cancelled_reservation=None, new_reservation=new_reservation, user_creating_reservation=request.user, explicit_policy_override=explicit_policy_override)

	# If there was a policy problem with the reservation then return the error...
	if policy_problems:
		return render(request, 'calendar/policy_dialog.html', {'policy_problems': policy_problems, 'overridable': overridable and request.user.is_staff, 'reservation_action': 'create'})

	# All policy checks have passed.

	# If the user only has one project then associate it with the reservation.
	# Otherwise, present a dialog box for the user to choose which project to associate.
	if not user.is_staff:
		active_projects = user.active_projects()
		if len(active_projects) == 1:
			new_reservation.project = active_projects[0]
		else:
			try:
				new_reservation.project = Project.objects.get(id=request.POST['project_id'])
			except:
				return render(request, 'calendar/project_choice.html', {'active_projects': active_projects})

		# Check if we are allowed to bill to project
		try:
			check_billing_to_project(new_reservation.project, user, new_reservation.reservation_item)
		except ProjectChargeException as e:
			policy_problems.append(e.msg)
			return render(request, 'calendar/policy_dialog.html', {'policy_problems': policy_problems, 'overridable': False, 'reservation_action': 'create'})

	# Reservation questions if applicable
	reservation_questions = get_and_combine_reservation_questions(item_type, item_id, new_reservation.project)
	if reservation_questions:
		dynamic_form = DynamicForm(reservation_questions)
		dynamic_form_rendered = dynamic_form.render()
		if not bool(request.POST.get("reservation_questions", False)):
			# We have not yet asked the questions
			return render(request, 'calendar/reservation_questions.html', {'reservation_questions': dynamic_form_rendered})
		else:
			# We already asked before, now we need to extract the results
			try:
				new_reservation.question_data = dynamic_form.extract(request)
			except RequiredUnansweredQuestionsException as e:
				dictionary = {'error': str(e), 'reservation_questions': dynamic_form_rendered}
				return render(request, 'calendar/reservation_questions.html', dictionary)

	# Configuration rules only apply to tools
	if item_type == ReservationItemType.TOOL:
		configured = (request.POST.get('configured') == "true")
		# If a reservation is requested and the tool does not require configuration...
		if not item.is_configurable():
			new_reservation.save_and_notify()
			return reservation_success(request, new_reservation)

		# If a reservation is requested and the tool requires configuration that has not been submitted...
		elif item.is_configurable() and not configured:
			configuration_information = item.get_configuration_information(user=user, start=start)
			return render(request, 'calendar/configuration.html', configuration_information)

		# If a reservation is requested and configuration information is present also...
		elif item.is_configurable() and configured:
			new_reservation.additional_information, new_reservation.self_configuration = extract_configuration(request)
			# Reservation can't be short notice if the user is configuring the tool themselves.
			if new_reservation.self_configuration:
				new_reservation.short_notice = False
			new_reservation.save_and_notify()
			return reservation_success(request, new_reservation)

	elif item_type == ReservationItemType.AREA:
		new_reservation.save_and_notify()
		return HttpResponse()

	return HttpResponseBadRequest("Reservation creation failed because invalid parameters were sent to the server.")


def reservation_success(request, reservation: Reservation):
	""" Checks area capacity and display warning message if capacity is high """
	max_area_overlap, max_location_overlap = (0,0)
	max_area_time, max_location_time = (None, None)
	area: Area = reservation.tool.requires_area_access if reservation.reservation_item_type == ReservationItemType.TOOL else reservation.area
	location = reservation.tool.location if reservation.reservation_item_type == ReservationItemType.TOOL else None
	if area and area.reservation_warning:
		overlapping_reservations_in_same_area = Reservation.objects.filter(cancelled=False, missed=False, shortened=False, end__gte=reservation.start, start__lte=reservation.end)
		if reservation.reservation_item_type == ReservationItemType.TOOL:
			overlapping_reservations_in_same_area = overlapping_reservations_in_same_area.filter(tool__in=Tool.objects.filter(_requires_area_access=area))
		elif reservation.reservation_item_type == ReservationItemType.AREA:
			overlapping_reservations_in_same_area = overlapping_reservations_in_same_area.filter(area=area)
		max_area_overlap, max_area_time = maximum_users_in_overlapping_reservations(overlapping_reservations_in_same_area)
		if location:
			overlapping_reservations_in_same_location = overlapping_reservations_in_same_area.filter(tool__in=Tool.objects.filter(_location=location))
			max_location_overlap, max_location_time = maximum_users_in_overlapping_reservations(overlapping_reservations_in_same_location)
	if max_area_overlap and max_area_overlap >= area.warning_capacity():
		dictionary = {
			'area': area,
			'location': location,
			'max_area_count': max_area_overlap,
			'max_location_count': max_location_overlap,
			'max_area_time': max(max_area_time, reservation.start),
			'max_location_time': max(max_location_time, reservation.start) if max_location_time else None,
		}
		return render(request, 'calendar/reservation_warning.html', dictionary, status=201) # send 201 code CREATED to indicate success but with more information to come
	else:
		return HttpResponse()


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
	""" Create an outage. """
	try:
		start, end = extract_times(request.POST)
		item_type = ReservationItemType(request.POST['item_type'])
		item_id = request.POST.get('item_id')
	except Exception as e:
		return HttpResponseBadRequest(str(e))
	item = get_object_or_404(item_type.get_object_class(), id=item_id)
	# Create the new reservation:
	outage = ScheduledOutage()
	outage.creator = request.user
	outage.category = request.POST.get('category', '')[:200]
	outage.outage_item = item
	outage.start = start
	outage.end = end

	# If there is a policy problem for the outage then return the error...
	policy_problem = check_policy_to_create_outage(outage)
	if policy_problem:
		return HttpResponseBadRequest(policy_problem)

	# Make sure there is at least an outage title
	if not request.POST.get('title'):
		calendar_outage_recurrence_limit = get_customization("calendar_outage_recurrence_limit")
		dictionary = {
			'categories': ScheduledOutageCategory.objects.all(),
			'recurrence_intervals': recurrence_frequency_display,
			'recurrence_date_start': start.date(),
			'calendar_outage_recurrence_limit': calendar_outage_recurrence_limit,
		}
		return render(request, 'calendar/scheduled_outage_information.html', dictionary)

	outage.title = request.POST['title']
	outage.details = request.POST.get('details', '')

	if request.POST.get('recurring_outage') == 'on':
		# we have to remove tz before creating rules otherwise 8am would become 7am after DST change for example.
		start_no_tz = outage.start.replace(tzinfo=None)
		end_no_tz = outage.end.replace(tzinfo=None)

		submitted_frequency = request.POST.get('recurrence_frequency')
		submitted_date_until = request.POST.get('recurrence_until', None)
		date_until = end.replace(hour=0, minute=0, second=0)
		if submitted_date_until:
			date_until = localize(datetime.strptime(submitted_date_until, '%m/%d/%Y'))
		date_until += timedelta(days=1, seconds=-1) # set at the end of the day
		by_week_day = None
		if submitted_frequency == 'DAILY_WEEKDAYS':
			by_week_day = (rrule.MO, rrule.TU, rrule.WE, rrule.TH, rrule.FR)
		elif submitted_frequency == 'DAILY_WEEKENDS':
			by_week_day = (rrule.SA, rrule.SU)
		frequency = recurrence_frequencies.get(submitted_frequency, rrule.DAILY)
		rules: Iterable[datetime] = rrule.rrule(dtstart=start, freq=frequency, interval=int(request.POST.get('recurrence_interval',1)), until=date_until, byweekday=by_week_day)
		for rule in list(rules):
			recurring_outage = ScheduledOutage()
			recurring_outage.creator = outage.creator
			recurring_outage.category = outage.category
			recurring_outage.outage_item = outage.outage_item
			recurring_outage.title = outage.title
			recurring_outage.details = outage.details
			recurring_outage.start = localize(start_no_tz.replace(year=rule.year, month=rule.month, day=rule.day))
			recurring_outage.end = localize(end_no_tz.replace(year=rule.year, month=rule.month, day=rule.day))
			recurring_outage.save()
	else:
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
		reservation_to_cancel = Reservation.objects.get(pk=request.POST.get('id'))
	except Reservation.DoesNotExist:
		return HttpResponseNotFound("The reservation that you wish to modify doesn't exist!")
	explicit_policy_override = False
	try:
		explicit_policy_override = request.POST['explicit_policy_override'] == 'true'
	except:
		pass
	# Record the current time so that the timestamp of the cancelled reservation and the new reservation match exactly.
	now = timezone.now()
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
	elif new_reservation.tool:
		new_reservation.short_notice = determine_insufficient_notice(reservation_to_cancel.tool, new_reservation.start)
	# A change in end time will always be provided for reservation move and resize operations.
	new_reservation.end = reservation_to_cancel.end + end_delta
	new_reservation.reservation_item = reservation_to_cancel.reservation_item
	new_reservation.project = reservation_to_cancel.project
	new_reservation.user = reservation_to_cancel.user
	new_reservation.creation_time = now

	response = check_policy_to_cancel_reservation(request.user, reservation_to_cancel, new_reservation)
	# Do not move the reservation if the user was not authorized to cancel it.
	if response.status_code != HTTPStatus.OK:
		return response

	# Cancel the user's original reservation.
	reservation_to_cancel.cancelled = True
	reservation_to_cancel.cancellation_time = now
	reservation_to_cancel.cancelled_by = request.user

	policy_problems, overridable = check_policy_to_save_reservation(cancelled_reservation=reservation_to_cancel, new_reservation=new_reservation, user_creating_reservation=request.user, explicit_policy_override=explicit_policy_override)
	if policy_problems:
		reservation_action = "resize" if start_delta is None else "move"
		return render(request, 'calendar/policy_dialog.html', {'policy_problems': policy_problems, 'overridable': overridable and request.user.is_staff, 'reservation_action': reservation_action})
	else:
		# All policy checks passed, so save the reservation.
		new_reservation.save_and_notify()
		reservation_to_cancel.descendant = new_reservation
		reservation_to_cancel.save_and_notify()
	return reservation_success(request, new_reservation)


def modify_outage(request, start_delta, end_delta):
	try:
		outage = ScheduledOutage.objects.get(pk=request.POST.get('id'))
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
	""" Determines if a reservation is created that does not give
	the staff sufficient advance notice to configure a tool. """
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

	reason = parse_parameter_string(request.POST, 'reason')
	response = cancel_the_reservation(reservation=reservation, user_cancelling_reservation=request.user, reason=reason)

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
		dictionary = {'event_type': 'Scheduled outage', 'tool': outage.tool, 'area': outage.area}
		return render(request, 'mobile/cancellation_result.html', dictionary)


@staff_member_required(login_url=None)
@require_POST
def set_reservation_title(request, reservation_id):
	""" Change reservation title for a user. """
	reservation = get_object_or_404(Reservation, id=reservation_id)
	reservation.title = request.POST.get('title', '')[:reservation._meta.get_field('title').max_length]
	reservation.save()
	return HttpResponse()


@login_required
@require_POST
def change_reservation_project(request, reservation_id):
	""" Change reservation project for a user. """
	reservation = get_object_or_404(Reservation, id=reservation_id)
	project = get_object_or_404(Project, id=request.POST['project_id'])
	if (request.user.is_staff or request.user == reservation.user) and reservation.has_not_ended() and reservation.has_not_started() and  project in reservation.user.active_projects():
		reservation.project = project
		reservation.save()
	return HttpResponse()


@login_required
@permission_required('NEMO.trigger_timed_services', raise_exception=True)
@require_GET
def email_reservation_reminders(request):
	return send_email_reservation_reminders()


def send_email_reservation_reminders():
	# Exit early if the reservation reminder email template has not been customized for the organization yet.
	reservation_reminder_message = get_media_file_contents('reservation_reminder_email.html')
	reservation_warning_message = get_media_file_contents('reservation_warning_email.html')
	if not reservation_reminder_message or not reservation_warning_message:
		calendar_logger.error("Reservation reminder email couldn't be send because either reservation_reminder_email.html or reservation_warning_email.html is not defined")
		return HttpResponseNotFound('The reservation reminder and/or warning email templates have not been customized for your organization yet. Please visit the customization page to upload both templates, then reservation reminder email notifications can be sent.')

	# Find all reservations that are two hours from now, plus or minus 5 minutes to allow for time skew.
	preparation_time = 120
	tolerance = 5
	earliest_start = timezone.now() + timedelta(minutes=preparation_time) - timedelta(minutes=tolerance)
	latest_start = timezone.now() + timedelta(minutes=preparation_time) + timedelta(minutes=tolerance)
	upcoming_reservations = Reservation.objects.filter(cancelled=False, start__gt=earliest_start, start__lt=latest_start)
	# Email a reminder to each user with an upcoming reservation.
	for reservation in upcoming_reservations:
		item = reservation.reservation_item
		item_type = reservation.reservation_item_type
		if item_type == ReservationItemType.TOOL and item.operational and not item.problematic() and item.all_resources_available()\
				or item_type == ReservationItemType.AREA and not item.required_resource_is_unavailable():
			subject = item.name + " reservation reminder"
			rendered_message = Template(reservation_reminder_message).render(Context({'reservation': reservation, 'template_color': bootstrap_primary_color('success')}))
		elif (item_type == ReservationItemType.TOOL and not item.operational) or item.required_resource_is_unavailable():
			subject = item.name + " reservation problem"
			rendered_message = Template(reservation_warning_message).render(Context({'reservation': reservation, 'template_color': bootstrap_primary_color('danger'), 'fatal_error': True}))
		else:
			subject = item.name + " reservation warning"
			rendered_message = Template(reservation_warning_message).render(Context({'reservation': reservation, 'template_color': bootstrap_primary_color('warning'), 'fatal_error': False}))
		user_office_email = get_customization('user_office_email_address')
		reservation.user.email_user(subject=subject, content=rendered_message, from_email=user_office_email, email_category=EmailCategory.TIMED_SERVICES)
	return HttpResponse()


@login_required
@permission_required('NEMO.trigger_timed_services', raise_exception=True)
@require_GET
def email_reservation_ending_reminders(request):
	return send_email_reservation_ending_reminders()


def send_email_reservation_ending_reminders():
	# Exit early if the reservation ending reminder email template has not been customized for the organization yet.
	reservation_ending_reminder_message = get_media_file_contents('reservation_ending_reminder_email.html')
	user_office_email = get_customization('user_office_email_address')
	if not reservation_ending_reminder_message:
		calendar_logger.error("Reservation ending reminder email couldn't be send because either reservation_ending_reminder_email.html is not defined")
		return HttpResponseNotFound('The reservation ending reminder template has not been customized for your organization yet. Please visit the customization page to upload one, then reservation ending reminder email notifications can be sent.')

	# We only send ending reservation reminders to users that are currently logged in
	current_logged_in_user = AreaAccessRecord.objects.filter(end=None, staff_charge=None, customer__is_staff=False)
	valid_reservations = Reservation.objects.filter(cancelled=False, missed=False, shortened=False)
	user_area_reservations = valid_reservations.filter(area__isnull=False, user__in=current_logged_in_user.values_list('customer', flat=True))

	# Find all reservations that end 30 or 15 min from now, plus or minus 3 minutes to allow for time skew.
	reminder_times = [30,15]
	tolerance = 3
	time_filter = Q()
	for reminder_time in reminder_times:
		earliest_end = timezone.now() + timedelta(minutes=reminder_time) - timedelta(minutes=tolerance)
		latest_end = timezone.now() + timedelta(minutes=reminder_time) + timedelta(minutes=tolerance)
		new_filter = Q(end__gt=earliest_end, end__lt=latest_end)
		time_filter = time_filter | new_filter
	ending_reservations = user_area_reservations.filter(time_filter)
	# Email a reminder to each user with an reservation ending soon.
	for reservation in ending_reservations:
		subject = reservation.reservation_item.name + " reservation ending soon"
		rendered_message = Template(reservation_ending_reminder_message).render(Context({'reservation': reservation}))
		reservation.user.email_user(subject=subject, content=rendered_message, from_email=user_office_email, email_category=EmailCategory.TIMED_SERVICES)
	return HttpResponse()


@login_required
@permission_required('NEMO.trigger_timed_services', raise_exception=True)
@require_GET
def email_usage_reminders(request):
	projects_to_exclude = request.GET.getlist("projects_to_exclude[]")
	return send_email_usage_reminders(projects_to_exclude)


def send_email_usage_reminders(projects_to_exclude=None):
	if projects_to_exclude is None:
		projects_to_exclude = []
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
			'resources_in_use': [access_record.area.name],
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
	facility_name = get_customization('facility_name')
	if message:
		subject = f"{facility_name} usage"
		for user in aggregate.values():
			rendered_message = Template(message).render(Context({'user': user}))
			send_mail(subject=subject, content=rendered_message, from_email=user_office_email, to=[user['email']], email_category=EmailCategory.TIMED_SERVICES)

	message = get_media_file_contents('staff_charge_reminder_email.html')
	if message:
		busy_staff = StaffCharge.objects.filter(end=None)
		for staff_charge in busy_staff:
			subject = "Active staff charge since " + format_datetime(staff_charge.start)
			rendered_message = Template(message).render(Context({'staff_charge': staff_charge}))
			staff_charge.staff_member.email_user(subject=subject, content=rendered_message, from_email=user_office_email, email_category=EmailCategory.TIMED_SERVICES)

	return HttpResponse()


@login_required
@require_GET
def reservation_details(request, reservation_id):
	reservation = get_object_or_404(Reservation, id=reservation_id)
	if reservation.cancelled:
		error_message = 'This reservation was cancelled by {0} at {1}.'.format(reservation.cancelled_by, format_datetime(reservation.cancellation_time))
		return HttpResponseNotFound(error_message)
	reservation_project_can_be_changed = (request.user.is_staff or request.user == reservation.user) and reservation.has_not_ended and reservation.has_not_started and reservation.user.active_project_count() > 1
	return render(request, 'calendar/reservation_details.html', {'reservation': reservation, 'reservation_project_can_be_changed': reservation_project_can_be_changed})


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
	return do_cancel_unused_reservations()


def do_cancel_unused_reservations():
	"""
	Missed reservation for tools is when there is no tool activity during the reservation time + missed reservation threshold.
	Any tool usage will count, since we don't want to charge for missed reservation when users swap reservation or somebody else gets to use the tool.

	Missed reservation for areas is when there is no area access login during the reservation time + missed reservation threshold
	"""

	# Missed Tool Reservations
	tools = Tool.objects.filter(visible=True, _operational=True, _missed_reservation_threshold__isnull=False)
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
			if not (UsageEvent.objects.filter(tool_id__in=tool.get_family_tool_ids(), start__gte=threshold).exists() or UsageEvent.objects.filter(tool_id__in=tool.get_family_tool_ids(), end__gte=threshold).exists()):
				# Mark the reservation as missed and notify the user & staff.
				r.missed = True
				r.save()
				missed_reservations.append(r)

	# Missed Area Reservations
	areas = Area.objects.filter(missed_reservation_threshold__isnull=False)
	for area in areas:
		# if area has outage or required resource is unavailable, no need to look
		if area.required_resource_is_unavailable() or area.scheduled_outage_in_progress():
			continue

		# Calculate the timestamp of how long a user can be late for a reservation.
		threshold = (timezone.now() - timedelta(minutes=area.missed_reservation_threshold))
		threshold = datetime.replace(threshold, second=0, microsecond=0)  # Round down to the nearest minute.
		# Find the reservations that began exactly at the threshold.
		reservation = Reservation.objects.filter(cancelled=False, missed=False, shortened=False, area=area, user__is_staff=False, start=threshold, end__gt=timezone.now())
		for r in reservation:
			# Staff may abandon reservations.
			if r.user.is_staff:
				continue
			# if there was no area access starting or ending since the threshold timestamp then we assume the reservation was missed
			if not (AreaAccessRecord.objects.filter(area__id=area.id, customer=r.user, start__gte=threshold).exists() or AreaAccessRecord.objects.filter(area__id=area.id, customer=r.user, end__gte=threshold).exists()):
				# Mark the reservation as missed and notify the user & staff.
				r.missed = True
				r.save()
				missed_reservations.append(r)

	for r in missed_reservations:
		send_missed_reservation_notification(r)

	return HttpResponse()


@login_required
@require_GET
@permission_required('NEMO.trigger_timed_services', raise_exception=True)
def email_out_of_time_reservation_notification(request):
	return send_email_out_of_time_reservation_notification()


def send_email_out_of_time_reservation_notification():
	"""
	Out of time reservation notification for areas is when a user is still logged in a area but his reservation expired.
	"""
	# Exit early if the out of time reservation email template has not been customized for the organization yet.
	# This feature only sends emails, so there if the template is not defined there nothing to do.
	if not get_media_file_contents('out_of_time_reservation_email.html'):
		return HttpResponseNotFound('The out of time reservation email template has not been customized for your organization yet. Please visit the customization page to upload a template, then out of time email notifications can be sent.')

	out_of_time_user_area = []

	# Find all logged users
	access_records:List[AreaAccessRecord] = AreaAccessRecord.objects.filter(end=None, staff_charge=None).prefetch_related('customer', 'area').only('customer', 'area')
	for access_record in access_records:
		# staff and service personnel are exempt from out of time notification
		customer = access_record.customer
		area = access_record.area
		if customer.is_staff or customer.is_service_personnel:
			continue

		if area.requires_reservation:
			# Calculate the timestamp of how late a user can be logged in after a reservation ended.
			threshold = timezone.now() if not area.logout_grace_period else timezone.now() - timedelta(minutes=area.logout_grace_period)
			threshold = datetime.replace(threshold, second=0, microsecond=0)  # Round down to the nearest minute.
			ending_reservations = Reservation.objects.filter(cancelled=False, missed=False, shortened=False, area=area, user=customer, start__lte=timezone.now(), end=threshold)
			# find out if a reservation is starting right at the same time (in case of back to back reservations, in which case customer is good)
			starting_reservations = Reservation.objects.filter(cancelled=False, missed=False, shortened=False, area=area, user=customer, start=threshold)
			if ending_reservations.exists() and not starting_reservations.exists():
				out_of_time_user_area.append(ending_reservations[0])

	for reservation in out_of_time_user_area:
		send_out_of_time_reservation_notification(reservation)

	return HttpResponse()


@staff_member_required(login_url=None)
@require_GET
def proxy_reservation(request):
	return render(request, 'calendar/proxy_reservation.html', {'users': User.objects.filter(is_active=True)})


def get_and_combine_reservation_questions(item_type: ReservationItemType, item_id: int, project: Project = None) -> str:
	reservation_questions = ReservationQuestions.objects.all()
	if item_type == ReservationItemType.TOOL:
		reservation_questions = reservation_questions.filter(tool_reservations=True)
		reservation_questions = reservation_questions.filter(Q(only_for_tools=None) | Q(only_for_tools__in=[item_id]))
	if item_type == ReservationItemType.AREA:
		reservation_questions = reservation_questions.filter(area_reservations=True)
		reservation_questions = reservation_questions.filter(Q(only_for_areas=None) | Q(only_for_areas__in=[item_id]))
	if project:
		reservation_questions = reservation_questions.filter(Q(only_for_projects=None) | Q(only_for_projects__in=[project.id]))
	else:
		reservation_questions = reservation_questions.filter(only_for_projects=None)
	reservation_questions_json = []
	for reservation_question in reservation_questions:
		reservation_questions_json.extend(loads(reservation_question.questions))
	return dumps(reservation_questions_json) if len(reservation_questions_json) else ""


def shorten_reservation(user: User, item: Union[Area, Tool], new_end: datetime = None):
	try:
		if new_end is None:
			new_end = timezone.now()
		current_reservation = Reservation.objects.filter(start__lt=timezone.now(), end__gt=timezone.now(),
														 cancelled=False, missed=False, shortened=False, user=user)
		current_reservation = current_reservation.get(**{ReservationItemType.from_item(item).value: item})
		# Staff are exempt from mandatory reservation shortening.
		if user.is_staff is False:
			new_reservation = deepcopy(current_reservation)
			new_reservation.id = None
			new_reservation.pk = None
			new_reservation.end = new_end
			new_reservation.save()
			current_reservation.shortened = True
			current_reservation.descendant = new_reservation
			current_reservation.save()
	except Reservation.DoesNotExist:
		pass


def cancel_the_reservation(reservation: Reservation, user_cancelling_reservation: User, reason: Optional[str]):
	# Check policy to cancel reservation contains rules common to cancelling and modifying
	response = check_policy_to_cancel_reservation(user_cancelling_reservation, reservation)

	# The following rules apply only for proper cancellation, not for modification
	# Staff must provide a reason when cancelling a reservation they do not own.
	if reservation.user != user_cancelling_reservation and not reason:
		response = HttpResponseBadRequest("You must provide a reason when cancelling someone else's reservation.")

	policy_problems = []
	check_tool_reservation_requiring_area(policy_problems, user_cancelling_reservation, reservation, None)
	if policy_problems:
		return HttpResponseBadRequest(policy_problems[0])

	if response.status_code == HTTPStatus.OK:
		# All policy checks passed, so cancel the reservation.
		reservation.cancelled = True
		reservation.cancellation_time = timezone.now()
		reservation.cancelled_by = user_cancelling_reservation

		if reason:
			''' don't notify (just save) in this case since we are sending a specific email for the cancellation '''
			reservation.save()
			email_contents = get_media_file_contents('cancellation_email.html')
			if email_contents:
				dictionary = {
					'staff_member': user_cancelling_reservation,
					'reservation': reservation,
					'reason': reason,
					'template_color': bootstrap_primary_color('info')
				}
				cancellation_email = Template(email_contents).render(Context(dictionary))
				recipients = [reservation.user.email]
				if reservation.area:
					recipients.extend(reservation.area.reservation_email_list())
				if reservation.user.get_preferences().attach_cancelled_reservation:
					attachment = create_ics_for_reservation(reservation, cancelled=True)
					send_mail(subject='Your reservation was cancelled', content=cancellation_email, from_email=user_cancelling_reservation.email, to=recipients, attachments=[attachment])
				else:
					send_mail(subject='Your reservation was cancelled', content=cancellation_email, from_email=user_cancelling_reservation.email, to=recipients)

		else:
			''' here the user cancelled his own reservation so notify him '''
			reservation.save_and_notify()

	return response


def send_missed_reservation_notification(reservation):
	message = get_media_file_contents('missed_reservation_email.html')
	user_office_email = get_customization('user_office_email_address')
	abuse_email = get_customization('abuse_email_address')
	if message and user_office_email:
		subject = "Missed reservation for the " + str(reservation.reservation_item)
		message = Template(message).render(Context({'reservation': reservation}))
		send_mail(subject=subject, content=message, from_email=user_office_email, to=[reservation.user.email, abuse_email, user_office_email], email_category=EmailCategory.TIMED_SERVICES)
	else:
		calendar_logger.error("Missed reservation email couldn't be send because missed_reservation_email.html or user_office_email are not defined")


def send_out_of_time_reservation_notification(reservation:Reservation):
	message = get_media_file_contents('out_of_time_reservation_email.html')
	user_office_email = get_customization('user_office_email_address')
	if message and user_office_email:
		subject = "Out of time in the " + str(reservation.area.name)
		message = Template(message).render(Context({'reservation': reservation}))
		recipients = [reservation.user.email]
		recipients.extend(reservation.area.abuse_email_list())
		send_mail(subject=subject, content=message, from_email=user_office_email, to=recipients, email_category=EmailCategory.TIMED_SERVICES)
	else:
		calendar_logger.error("Out of time reservation email couldn't be send because out_of_time_reservation_email.html or user_office_email are not defined")


def send_user_created_reservation_notification(reservation: Reservation):
	site_title = get_customization('site_title')
	recipients = [reservation.user.email] if reservation.user.get_preferences().attach_created_reservation else []
	if reservation.area:
		recipients.extend(reservation.area.reservation_email_list())
	if recipients:
		subject = f"[{site_title}] Reservation for the " + str(reservation.reservation_item)
		message = get_media_file_contents('reservation_created_user_email.html')
		message = Template(message).render(Context({'reservation': reservation}))
		user_office_email = get_customization('user_office_email_address')
		# We don't need to check for existence of reservation_created_user_email because we are attaching the ics reservation and sending the email regardless (message will be blank)
		if user_office_email:
			attachment = create_ics_for_reservation(reservation)
			send_mail(subject=subject, content=message, from_email=user_office_email, to=recipients, attachments=[attachment])
		else:
			calendar_logger.error("User created reservation notification could not be send because user_office_email_address is not defined")


def send_user_cancelled_reservation_notification(reservation: Reservation):
	site_title = get_customization('site_title')
	recipients = [reservation.user.email] if reservation.user.get_preferences().attach_cancelled_reservation else []
	if reservation.area:
		recipients.extend(reservation.area.reservation_email_list())
	if recipients:
		subject = f"[{site_title}] Cancelled Reservation for the " + str(reservation.reservation_item)
		message = get_media_file_contents('reservation_cancelled_user_email.html')
		message = Template(message).render(Context({'reservation': reservation}))
		user_office_email = get_customization('user_office_email_address')
		# We don't need to check for existence of reservation_cancelled_user_email because we are attaching the ics reservation and sending the email regardless (message will be blank)
		if user_office_email:
			attachment = create_ics_for_reservation(reservation, cancelled=True)
			send_mail(subject=subject, content=message, from_email=user_office_email, to=recipients, attachments=[attachment])
		else:
			calendar_logger.error("User cancelled reservation notification could not be send because user_office_email_address is not defined")


def create_ics_for_reservation(reservation: Reservation, cancelled=False):
	site_title = get_customization('site_title')
	method_name = 'CANCEL' if cancelled else 'REQUEST'
	method = f'METHOD:{method_name}\n'
	status = 'STATUS:CANCELLED\n' if cancelled else 'STATUS:CONFIRMED\n'
	uid = 'UID:'+str(reservation.id)+'\n'
	sequence = 'SEQUENCE:2\n' if cancelled else 'SEQUENCE:0\n'
	priority = 'PRIORITY:5\n' if cancelled else 'PRIORITY:0\n'
	now = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
	start = reservation.start.astimezone(pytz.utc).strftime('%Y%m%dT%H%M%SZ')
	end = reservation.end.astimezone(pytz.utc).strftime('%Y%m%dT%H%M%SZ')
	reservation_name = reservation.reservation_item.name
	lines = ['BEGIN:VCALENDAR\n', 'VERSION:2.0\n', method, 'BEGIN:VEVENT\n', uid, sequence, priority, f'DTSTAMP:{now}\n', f'DTSTART:{start}\n', f'DTEND:{end}\n', f'ATTENDEE:{reservation.user.email}\n', f'ORGANIZER:{reservation.user.email}\n', f'SUMMARY:[{site_title}] {reservation_name} Reservation\n', status, 'END:VEVENT\n', 'END:VCALENDAR\n']
	ics = io.StringIO('')
	ics.writelines(lines)
	ics.seek(0)

	attachment = create_email_attachment(ics, maintype='text', subtype='calendar', method=method_name)
	return attachment
