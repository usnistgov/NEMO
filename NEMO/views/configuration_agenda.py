from datetime import timedelta

from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render
from django.views.decorators.http import require_GET

from NEMO.models import Tool, Reservation
from NEMO.utilities import localize, naive_local_current_datetime


@staff_member_required(login_url=None)
@require_GET
def configuration_agenda(request, time_period='today'):
	tools = Tool.objects.exclude(configuration__isnull=True).exclude(configuration__exclude_from_configuration_agenda=True).values_list('id', flat=True)
	start = None
	end = None
	if time_period == 'today':
		start = naive_local_current_datetime().replace(tzinfo=None)
		end = naive_local_current_datetime().replace(hour=23, minute=59, second=59, microsecond=999, tzinfo=None)
	elif time_period == 'near_future':
		start = naive_local_current_datetime().replace(hour=23, minute=59, second=59, microsecond=999, tzinfo=None)
		if start.weekday() == 4:  # If it's Friday, then the 'near future' is Saturday, Sunday, and Monday
			end = start + timedelta(days=3)
		else:  # If it's not Friday, then the 'near future' is the next day
			end = start + timedelta(days=1)
	start = localize(start)
	end = localize(end)
	reservations = Reservation.objects.filter(start__gt=start, start__lt=end, tool__id__in=tools, self_configuration=False, cancelled=False, missed=False, shortened=False).exclude(additional_information='').order_by('start')
	tools = Tool.objects.filter(id__in=reservations.values_list('tool', flat=True))
	configuration_widgets = {}
	for tool in tools:
		configuration_widgets[tool.id] = tool.configuration_widget(request.user)
	dictionary = {
		'time_period': time_period,
		'tools': tools,
		'reservations': reservations,
		'configuration_widgets': configuration_widgets
	}
	return render(request, 'configuration_agenda.html', dictionary)
