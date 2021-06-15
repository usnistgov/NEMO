from datetime import datetime, timedelta
from itertools import chain

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import HttpResponseBadRequest
from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_time, parse_date
from django.views.decorators.http import require_GET, require_POST

from NEMO.exceptions import ProjectChargeException, RequiredUnansweredQuestionsException
from NEMO.models import Reservation, Tool, Project, ScheduledOutage, User, Area, ReservationItemType
from NEMO.utilities import extract_date, localize, beginning_of_the_day, end_of_the_day
from NEMO.views.calendar import extract_configuration, determine_insufficient_notice, get_and_combine_reservation_questions
from NEMO.views.customization import get_customization
from NEMO.views.policy import check_policy_to_save_reservation, check_billing_to_project
from NEMO.widgets.dynamic_form import DynamicForm


@login_required
@require_GET
def choose_item(request, next_page):
	user: User = request.user
	tools = Tool.objects.filter(visible=True).order_by('_category', 'name')
	dictionary = {
		'tools': list(tools),
		'areas': [],
	}
	if next_page == 'view_calendar':
		# If the user has no active projects then they're not allowed to make reservations. Redirect them home.
		if user.active_project_count() == 0:
			return render(request, 'mobile/no_active_projects.html')
		areas = Area.objects.filter(requires_reservation=True).only('name')
		# We want to remove areas the user doesn't have access to
		display_all_areas = get_customization('calendar_display_not_qualified_areas') == 'enabled'
		if not display_all_areas and areas and user and not user.is_superuser:
			areas = [area for area in areas if area in user.accessible_areas()]

		tool_area = 'tool/area'
		if tools and not areas:
			tool_area = 'tool'
		if areas and not tools:
			tool_area = 'area'

		dictionary['areas'] = list(areas)
		dictionary['title'] = f"Which {tool_area} calendar would you like to view?"
		dictionary['next_page'] = 'view_calendar'
	elif next_page == 'tool_control':
		dictionary['title'] = "Which tool control page would you like to view?"
		dictionary['next_page'] = 'tool_control'
	return render(request, 'mobile/choose_item.html', dictionary)


@login_required
@require_GET
def new_reservation(request, item_type, item_id, date=None):
	# If the user has no active projects then they're not allowed to make reservations.
	user: User = request.user
	if user.active_project_count() == 0:
		return render(request, 'mobile/no_active_projects.html')

	item_type = ReservationItemType(item_type)
	item = get_object_or_404(item_type.get_object_class(), id=item_id)
	if item_type == ReservationItemType.TOOL:
		dictionary = item.get_configuration_information(user=request.user, start=None)
	else:
		dictionary = {}
	dictionary['item'] = item
	dictionary['item_type'] = item_type.value
	dictionary['date'] = date
	dictionary['item_reservation_times'] = list(Reservation.objects.filter(**{item_type.value: item}).filter(cancelled=False, missed=False, shortened=False, start__gte=timezone.now()))

	# Reservation questions if applicable
	if not user.is_staff:
		reservation_question_dict = {}
		for project in user.active_projects():
			reservation_questions = get_and_combine_reservation_questions(item_type, item_id, project)
			if reservation_questions:
				dynamic_form = DynamicForm(reservation_questions)
				reservation_question_dict[project.id] = dynamic_form.render()
		dictionary['reservation_questions'] = reservation_question_dict

	return render(request, 'mobile/new_reservation.html', dictionary)


@login_required
@require_POST
def make_reservation(request):
	""" Create a reservation for a user. """
	try:
		date = parse_date(request.POST['date'])
		start = localize(datetime.combine(date, parse_time(request.POST['start'])))
		end = localize(datetime.combine(date, parse_time(request.POST['end'])))
	except:
		return render(request, 'mobile/error.html', {'message': 'Please enter a valid date, start time, and end time for the reservation.'})
	item_type = ReservationItemType(request.POST['item_type'])
	item = get_object_or_404(item_type.get_object_class(), id=request.POST.get('item_id'))
	# Create the new reservation:
	reservation = Reservation()
	reservation.user = request.user
	reservation.creator = request.user
	reservation.reservation_item = item
	reservation.start = start
	reservation.end = end
	if item_type == ReservationItemType.TOOL:
		reservation.short_notice = determine_insufficient_notice(item, start)
	else:
		reservation.short_notice = False
	policy_problems, overridable = check_policy_to_save_reservation(cancelled_reservation=None, new_reservation=reservation, user_creating_reservation=request.user, explicit_policy_override=False)

	# If there was a problem in saving the reservation then return the error...
	if policy_problems:
		return render(request, 'mobile/error.html', {'message': policy_problems[0]})

	# All policy checks have passed.
	try:
		reservation.project = Project.objects.get(id=request.POST['project_id'])
		# Check if we are allowed to bill to project
		check_billing_to_project(reservation.project, request.user, reservation.reservation_item)
	except ProjectChargeException as e:
		return render(request, 'mobile/error.html', {'message': e.msg})
	except:
		if not request.user.is_staff:
			return render(request, 'mobile/error.html', {'message': 'You must specify a project for your reservation'})

	reservation.additional_information, reservation.self_configuration = extract_configuration(request)
	# Reservation can't be short notice if the user is configuring the tool themselves.
	if reservation.self_configuration:
		reservation.short_notice = False

	# Reservation questions if applicable
	reservation_questions = get_and_combine_reservation_questions(item_type, item.id, reservation.project)
	if reservation_questions:
		try:
			dynamic_form = DynamicForm(reservation_questions)
			reservation.question_data = dynamic_form.extract(request)
		except RequiredUnansweredQuestionsException as e:
			return render(request, 'mobile/error.html', {'message': str(e)})

	reservation.save_and_notify()
	return render(request, 'mobile/reservation_success.html', {'new_reservation': reservation})


@login_required
@require_GET
def view_calendar(request, item_type, item_id, date=None):
	item_type = ReservationItemType(item_type)
	item = get_object_or_404(item_type.get_object_class(), id=item_id)
	if date:
		try:
			date = extract_date(date)
		except:
			render(request, 'mobile/error.html', {'message': 'Invalid date requested for tool calendar'})
			return HttpResponseBadRequest()
	else:
		date = datetime.now()

	start = beginning_of_the_day(date, in_local_timezone=True)
	end = end_of_the_day(date, in_local_timezone=True)

	reservations = Reservation.objects.filter(**{item_type.value: item}).filter(cancelled=False, missed=False, shortened=False).filter(**{})
	# Exclude events for which the following is true:
	# The event starts and ends before the time-window, and...
	# The event starts and ends after the time-window.
	reservations = reservations.exclude(start__lt=start, end__lt=start)
	reservations = reservations.exclude(start__gt=end, end__gt=end)

	outages = ScheduledOutage.objects.none()
	if item_type == ReservationItemType.TOOL:
		outages = ScheduledOutage.objects.filter(Q(tool=item) | Q(resource__fully_dependent_tools__in=[item]))
	elif item_type == ReservationItemType.AREA:
		outages = item.scheduled_outage_queryset()

	# Exclude outages for which the following is true:
	# The outage starts and ends before the time-window, and...
	# The outage starts and ends after the time-window.
	outages = outages.exclude(start__lt=start, end__lt=start)
	outages = outages.exclude(start__gt=end, end__gt=end)

	events = list(chain(reservations, outages))
	events.sort(key=lambda x: x.start)

	dictionary = {
		'item': item,
		'item_type': item_type.value,
		'previous_day': start - timedelta(days=1),
		'current_day': start,
		'current_day_string': date.strftime('%Y-%m-%d'),
		'next_day': start + timedelta(days=1),
		'events': events,
	}

	return render(request, 'mobile/view_calendar.html', dictionary)
