from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET
from requests import get

from NEMO.models import AreaAccessRecord, ConsumableWithdraw, Reservation, StaffCharge, TrainingSession, UsageEvent
from NEMO.utilities import get_month_timeframe, month_list


@login_required
@require_GET
def usage(request):
	first_of_the_month, last_of_the_month = get_month_timeframe(request.GET.get('timeframe'))
	dictionary = {
		'area_access': AreaAccessRecord.objects.filter(customer=request.user, end__gt=first_of_the_month, end__lte=last_of_the_month),
		'consumables': ConsumableWithdraw.objects.filter(customer=request.user, date__gt=first_of_the_month, date__lte=last_of_the_month),
		'missed_reservations': Reservation.objects.filter(user=request.user, missed=True, end__gt=first_of_the_month, end__lte=last_of_the_month),
		'staff_charges': StaffCharge.objects.filter(customer=request.user, end__gt=first_of_the_month, end__lte=last_of_the_month),
		'training_sessions': TrainingSession.objects.filter(trainee=request.user, date__gt=first_of_the_month, date__lte=last_of_the_month),
		'usage_events': UsageEvent.objects.filter(user=request.user, end__gt=first_of_the_month, end__lte=last_of_the_month),
		'month_list': month_list(),
		'timeframe': request.GET.get('timeframe') or first_of_the_month.strftime('%B, %Y'),
	}
	dictionary['no_charges'] = not (dictionary['area_access'] or dictionary['consumables'] or dictionary['missed_reservations'] or dictionary['staff_charges'] or dictionary['training_sessions'] or dictionary['usage_events'])
	return render(request, 'usage.html', dictionary)


@login_required
@require_GET
def billing_information(request):
	dictionary = {}
	if not settings.BILLING_SERVICE['available']:
		return HttpResponse()
	try:
		url = settings.BILLING_SERVICE['url']
		keyword_arguments = settings.BILLING_SERVICE['keyword_arguments']
		dictionary['billing_information'] = get(url, params=None, **keyword_arguments).content.decode()
	except Exception as e:
		dictionary['billing_information'] = str(e)
	return HttpResponse(dictionary['billing_information'])
