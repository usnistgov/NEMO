from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET
from requests import get

from NEMO.models import AreaAccessRecord, ConsumableWithdraw, Reservation, StaffCharge, TrainingSession, UsageEvent, User
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
	return render(request, 'usage/usage.html', dictionary)


@login_required
@require_GET
def billing_information(request, timeframe=''):
	dictionary = {}
	if not settings.BILLING_SERVICE['available']:
		return HttpResponse()
	try:
		cost_activity_url = settings.BILLING_SERVICE['cost_activity_url']
		project_lead_url = settings.BILLING_SERVICE['project_lead_url']
		keyword_arguments = settings.BILLING_SERVICE['keyword_arguments']

		first_of_the_month, last_of_the_month = get_month_timeframe(timeframe)
		formatted_projects = ','.join(map(str, set(request.user.active_projects().values_list('application_identifier', flat=True))))
		cost_activity_params = {
			'created_date_gte': f"'{first_of_the_month.strftime('%m/%d/%Y')}'",
			'created_date_lt': f"'{last_of_the_month.strftime('%m/%d/%Y')}'",
			'application_names': f"'{formatted_projects}'",
			'$format': 'json'
		}
		cost_activity_response = get(cost_activity_url, params=cost_activity_params, **keyword_arguments)
		cost_activity_data = cost_activity_response.json()['d']

		latest_pis_params = {'$format': 'json'}
		latest_pis_response = get(project_lead_url, params=latest_pis_params, **keyword_arguments)
		latest_pis_data = latest_pis_response.json()['d']

		project_totals = {}
		application_totals = {}
		user_pi_applications = list()
		# Construct a tree of account, application, project, and member total spending
		cost_activities_tree = {}
		for activity in cost_activity_data:
			project_totals.setdefault(activity['project_id'], 0)
			application_totals.setdefault(activity['application_id'], 0)
			account_key = (activity['account_id'], activity['account_name'])
			application_key = (activity['application_id'], activity['application_name'])
			project_key = (activity['project_id'], activity['project_name'])
			user_key = (activity['member_id'], User.objects.get(id=activity['member_id']))
			user_is_pi = is_user_pi(request.user, next((x for x in latest_pis_data if x['application_name'] == activity['application_name']), None))
			if user_is_pi:
				user_pi_applications.append(activity['application_id'])
			if user_is_pi or str(request.user.id) == activity['member_id']:
				cost_activities_tree.setdefault((activity['account_id'], activity['account_name']), {})
				cost_activities_tree[account_key].setdefault(application_key, {})
				cost_activities_tree[account_key][application_key].setdefault(project_key, {})
				cost_activities_tree[account_key][application_key][project_key].setdefault(user_key, 0)
				cost = -activity['cost'] if activity['activity_type'] == 'refund_activity' else activity['cost']
				cost_activities_tree[account_key][application_key][project_key][user_key] = cost_activities_tree[account_key][application_key][project_key][user_key] + cost
				project_totals[activity['project_id']] = project_totals[activity['project_id']] + cost
				application_totals[activity['application_id']] = application_totals[activity['application_id']] + cost
		dictionary['spending'] = {
			'activities': cost_activities_tree,
			'project_totals': project_totals,
			'application_totals': application_totals,
			'user_pi_applications': user_pi_applications
		} if cost_activities_tree else {}
		return render(request, 'usage/billing.html', dictionary)
	except Exception as e:
		return HttpResponse(str(e))


def is_user_pi(user, application_pi_row):
	return application_pi_row is not None and (user.username == application_pi_row['username'] or (user.first_name == application_pi_row['first_name'] and user.last_name == application_pi_row['last_name']))
