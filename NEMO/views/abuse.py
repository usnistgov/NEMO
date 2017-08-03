from collections import defaultdict

from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import ValidationError
from django.http import HttpResponseBadRequest
from django.shortcuts import render
from django.views.decorators.http import require_GET

from NEMO.forms import ReservationAbuseForm
from NEMO.models import Reservation, Tool, User


@staff_member_required(login_url=None)
@require_GET
def abuse(request):
	dictionary = {'tools': Tool.objects.filter(visible=True)}
	try:
		form = ReservationAbuseForm(request.GET)
		if form.is_valid():
			intermediate_results = defaultdict(float)
			reservations = Reservation.objects.filter(start__gt=form.cleaned_data['start'], start__lte=form.cleaned_data['end'], cancelled=True, cancellation_time__isnull=False)
			if form.cleaned_data['target']:
				reservations = reservations.filter(tool__id=form.cleaned_data['target'])
			for r in reservations:
				cancellation_delta = (r.start - r.cancellation_time).total_seconds()
				if 0 < cancellation_delta < form.cleaned_data['cancellation_horizon']:
					penalty = ((form.cleaned_data['cancellation_horizon'] - cancellation_delta) / form.cleaned_data['cancellation_horizon']) * form.cleaned_data['cancellation_penalty']
					intermediate_results[r.user.id] += penalty
			final_results = {}
			for user_id, score in intermediate_results.items():
				user = User.objects.get(id=user_id)
				final_results[user] = int(score)
			sorted_results = sorted(final_results.items(), key=lambda x: x[1], reverse=True)
			dictionary['results'] = sorted_results
		else:
			form = ReservationAbuseForm()
	except ValidationError:
		form = ReservationAbuseForm()
	dictionary['form'] = form
	return render(request, 'abuse/abuse.html', dictionary)


@staff_member_required(login_url=None)
@require_GET
def user_drill_down(request):
	try:
		form = ReservationAbuseForm(request.GET)
		form.is_valid()
		abuser = User.objects.get(id=request.GET['user'])
		reservations = Reservation.objects.filter(start__gt=form.cleaned_data['start'], start__lte=form.cleaned_data['end'], cancelled=True, cancellation_time__isnull=False, user=abuser)
		if form.cleaned_data['target']:
			reservations = reservations.filter(tool__id=form.cleaned_data['target'])
		abuses = []
		for r in reservations:
			cancellation_delta = (r.start - r.cancellation_time).total_seconds()
			if 0 < cancellation_delta < form.cleaned_data['cancellation_horizon']:
				penalty = ((form.cleaned_data['cancellation_horizon'] - cancellation_delta) / form.cleaned_data['cancellation_horizon']) * form.cleaned_data['cancellation_penalty']
				delta = duration_string((r.start - r.cancellation_time).total_seconds())
				abuses.append({'penalty': penalty, 'start': r.start, 'cancelled': r.cancellation_time, 'delta': delta, 'tool_name': r.tool.name, 'id': r.id})
		return render(request, 'abuse/user_drill_down.html', {'abuses': abuses, 'abuser': abuser})
	except:
		return HttpResponseBadRequest()


def duration_string(duration_in_seconds):
	minutes, seconds = divmod(duration_in_seconds, 60)
	hours, minutes = divmod(minutes, 60)
	hours = int(hours)
	minutes = int(minutes)

	if hours == 0 and minutes == 0:
		return "Less than a minute"

	result = ""

	if hours == 1:
		result = "{0} hour".format(hours)
	elif hours > 1:
		result = "{0} hours".format(hours)

	if minutes == 1:
		if result != "":
			result += ", "
		result += "{0} minute".format(minutes)
	elif minutes > 1:
		if result != "":
			result += ", "
		result += "{0} minutes".format(minutes)

	return result
