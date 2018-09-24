from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.http import require_GET
from django.conf import settings

from NEMO.models import Reservation, UsageEvent, AreaAccessRecord, ConsumableWithdraw, StaffCharge, TrainingSession
from NEMO.utilities import month_list, get_month_timeframe
from NEMO.views import billing_service


@login_required
@require_GET
def nanofab_usage(request):
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

	if hasattr(settings, 'BILLING_SERVICE'):
		dictionary['spending'] = billing_service.get_usage_from_billing(request.user, first_of_the_month, last_of_the_month)

	dictionary['no_charges'] = not (dictionary['area_access'] or dictionary['consumables'] or dictionary['missed_reservations'] or dictionary['staff_charges'] or dictionary['training_sessions'] or dictionary['usage_events'] or dictionary['spending'])
	return render(request, 'nanofab_usage.html', dictionary)
