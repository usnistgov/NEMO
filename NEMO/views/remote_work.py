from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import F, Q
from django.http import HttpResponse
from django.shortcuts import render, get_object_or_404
from django.views.decorators.http import require_GET, require_POST

from NEMO.models import UsageEvent, StaffCharge, User
from NEMO.utilities import month_list, get_month_timeframe


@staff_member_required(login_url=None)
@require_GET
def remote_work(request):
	first_of_the_month, last_of_the_month = get_month_timeframe(request.GET.get('date'))
	operator = request.GET.get('operator')
	if operator:
		if operator == "all staff":
			operator = None
		else:
			operator = get_object_or_404(User, id=operator)
	else:
		operator = request.user
	usage_events = UsageEvent.objects.filter(operator__is_staff=True, start__gte=first_of_the_month, start__lte=last_of_the_month).exclude(operator=F('user'))
	staff_charges = StaffCharge.objects.filter(start__gte=first_of_the_month, start__lte=last_of_the_month)
	if operator:
		usage_events = usage_events.exclude(~Q(operator_id=operator.id))
		staff_charges = staff_charges.exclude(~Q(staff_member_id=operator.id))
	dictionary = {
		'usage': usage_events,
		'staff_charges': staff_charges,
		'staff_list': User.objects.filter(is_staff=True),
		'month_list': month_list(),
		'selected_staff': operator.id if operator else "all staff",
		'selected_month': request.GET.get('date'),
	}
	return render(request, 'remote_work.html', dictionary)


@staff_member_required(login_url=None)
@require_POST
def validate_staff_charge(request, staff_charge_id):
	staff_charge = get_object_or_404(StaffCharge, id=staff_charge_id)
	staff_charge.validated = True
	staff_charge.save()
	return HttpResponse()


@staff_member_required(login_url=None)
@require_POST
def validate_usage_event(request, usage_event_id):
	usage_event = get_object_or_404(UsageEvent, id=usage_event_id)
	usage_event.validated = True
	usage_event.save()
	return HttpResponse()
