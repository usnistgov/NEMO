from datetime import datetime, timedelta
from itertools import chain

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import HttpResponseBadRequest
from django.shortcuts import render, get_object_or_404
from django.utils.dateparse import parse_time, parse_date
from django.views.decorators.http import require_GET, require_POST

from NEMO.models import Reservation, Tool, Project, ScheduledOutage
from NEMO.utilities import extract_date, localize, beginning_of_the_day, end_of_the_day
from NEMO.views.calendar import extract_configuration, determine_insufficient_notice
from NEMO.views.policy import check_policy_to_save_reservation


@login_required
@require_GET
def choose_tool(request, next_page):
	dictionary = {
		'tools': Tool.objects.filter(visible=True).order_by('category', 'name'),
	}
	if next_page == 'view_calendar':
		# If the user has no active projects then they're not allowed to make reservations. Redirect them home.
		if request.user.active_project_count() == 0:
			return render(request, 'mobile/no_active_projects.html')
		dictionary['title'] = "Which tool calendar would you like to view?"
		dictionary['next_page'] = 'view_calendar'
	elif next_page == 'tool_control':
		dictionary['title'] = "Which tool control page would you like to view?"
		dictionary['next_page'] = 'tool_control'
	return render(request, 'mobile/choose_tool.html', dictionary)


@login_required
@require_GET
def new_reservation(request, tool_id, date=None):
	# If the user has no active projects then they're not allowed to make reservations.
	if request.user.active_project_count() == 0:
		return render(request, 'mobile/no_active_projects.html')

	tool = get_object_or_404(Tool, id=tool_id)
	dictionary = tool.get_configuration_information(user=request.user, start=None)
	dictionary['tool'] = tool
	dictionary['date'] = date

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
	tool = get_object_or_404(Tool, id=request.POST.get('tool_id'))
	# Create the new reservation:
	reservation = Reservation()
	reservation.user = request.user
	reservation.creator = request.user
	reservation.tool = tool
	reservation.start = start
	reservation.end = end
	reservation.short_notice = determine_insufficient_notice(tool, start)
	policy_problems, overridable = check_policy_to_save_reservation(None, reservation, request.user, False)

	# If there was a problem in saving the reservation then return the error...
	if policy_problems:
		return render(request, 'mobile/error.html', {'message': policy_problems[0]})

	# All policy checks have passed.
	try:
		reservation.project = Project.objects.get(id=request.POST['project_id'])
	except:
		if not request.user.is_staff:
			return render(request, 'mobile/error.html', {'message': 'You must specify a project for your reservation'})

	reservation.additional_information, reservation.self_configuration = extract_configuration(request)
	# Reservation can't be short notice if the user is configuring the tool themselves.
	if reservation.self_configuration:
		reservation.short_notice = False
	reservation.save()
	return render(request, 'mobile/reservation_success.html', {'new_reservation': reservation})


@login_required
@require_GET
def view_calendar(request, tool_id, date=None):
	tool = get_object_or_404(Tool, id=tool_id)
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

	reservations = Reservation.objects.filter(tool=tool, cancelled=False, missed=False, shortened=False)
	# Exclude events for which the following is true:
	# The event starts and ends before the time-window, and...
	# The event starts and ends after the time-window.
	reservations = reservations.exclude(start__lt=start, end__lt=start)
	reservations = reservations.exclude(start__gt=end, end__gt=end)

	outages = ScheduledOutage.objects.filter(Q(tool=tool) | Q(resource__fully_dependent_tools__in=[tool]))
	outages = outages.exclude(start__lt=start, end__lt=start)
	outages = outages.exclude(start__gt=end, end__gt=end)

	events = list(chain(reservations, outages))
	events.sort(key=lambda x: x.start)

	dictionary = {
		'tool': tool,
		'previous_day': start - timedelta(days=1),
		'current_day': start,
		'current_day_string': date.strftime('%Y-%m-%d'),
		'next_day': start + timedelta(days=1),
		'events': events,
	}

	return render(request, 'mobile/view_calendar.html', dictionary)
