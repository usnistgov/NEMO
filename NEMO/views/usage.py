from logging import getLogger

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_GET
from requests import get

from NEMO.models import AreaAccessRecord, ConsumableWithdraw, Reservation, StaffCharge, TrainingSession, UsageEvent, User, Project, Account
from NEMO.utilities import get_month_timeframe, month_list, parse_start_and_end_date


logger = getLogger(__name__)


# Class for Applications that can be used for autocomplete
class Application(object):
	def __init__(self, name):
		self.name = name
		self.id = name

	def __str__(self):
		return self.name


# We want to keep all the parameters of the request when switching tabs, so we are just replacing usage <-> billing urls
def get_url_for_other_tab(request):
	full_path_request = request.get_full_path()
	usage_url = reverse('usage')
	billing_url = reverse('billing')
	project_usage_url = reverse('project_usage')
	project_billing_url = reverse('project_billing')
	if project_usage_url in full_path_request:
		full_path_request = full_path_request.replace(project_usage_url, project_billing_url)
	elif project_billing_url in full_path_request:
		full_path_request = full_path_request.replace(project_billing_url, project_usage_url)
	elif usage_url in full_path_request:
		full_path_request = full_path_request.replace(usage_url, billing_url)
	elif billing_url in full_path_request:
		full_path_request = full_path_request.replace(billing_url, usage_url)
	return full_path_request


def get_project_applications():
	applications = []
	projects = Project.objects.filter(id__in=Project.objects.values('application_identifier').distinct().values_list('id', flat=True))
	for project in projects:
		if not any(list(filter(lambda app: app.name == project.application_identifier, applications))):
			applications.append(Application(project.application_identifier))
	return applications


def date_parameters_dictionary(request):
	dates = False
	if request.GET.get('start_date') and request.GET.get('end_date'):
		start_date, end_date = parse_start_and_end_date(request.GET.get('start_date'), request.GET.get('end_date'))
		dates = True
	else:
		start_date, end_date = get_month_timeframe(request.GET.get('timeframe'))
	dictionary = {
		'month_list': month_list(),
		'timeframe': request.GET.get('timeframe') or start_date.strftime('%B, %Y'),
		'start_date': start_date,
		'end_date': end_date,
		'dates': dates,
		'tab_url': get_url_for_other_tab(request)
	}
	return dictionary, start_date, end_date


@login_required
@require_GET
def usage(request):
	base_dictionary, start_date, end_date = date_parameters_dictionary(request)
	dictionary = {
		'area_access': AreaAccessRecord.objects.filter(customer=request.user, end__gt=start_date, end__lte=end_date),
		'consumables': ConsumableWithdraw.objects.filter(customer=request.user, date__gt=start_date, date__lte=end_date),
		'missed_reservations': Reservation.objects.filter(user=request.user, missed=True, end__gt=start_date, end__lte=end_date),
		'staff_charges': StaffCharge.objects.filter(customer=request.user, end__gt=start_date, end__lte=end_date),
		'training_sessions': TrainingSession.objects.filter(trainee=request.user, date__gt=start_date, date__lte=end_date),
		'usage_events': UsageEvent.objects.filter(user=request.user, end__gt=start_date, end__lte=end_date),
	}
	dictionary['no_charges'] = not (dictionary['area_access'] or dictionary['consumables'] or dictionary['missed_reservations'] or dictionary['staff_charges'] or dictionary['training_sessions'] or dictionary['usage_events'])
	return render(request, 'usage/usage.html', {**base_dictionary, **dictionary})


@login_required
@require_GET
def billing(request):
	base_dictionary, start_date, end_date = date_parameters_dictionary(request)
	formatted_applications = ','.join(map(str, set(request.user.active_projects().values_list('application_identifier', flat=True))))
	try:
		billing_dictionary = billing_dict(start_date, end_date, request.user, formatted_applications)
		return render(request, 'usage/billing.html', {**base_dictionary, **billing_dictionary})
	except Exception as e:
		logger.warning(str(e))
		return render(request, 'usage/billing.html', base_dictionary)


@staff_member_required(login_url=None)
@require_GET
def project_usage(request, kind=None, identifier=None):
	base_dictionary, start_date, end_date = date_parameters_dictionary(request)

	projects = []
	selection = ''
	try:
		if kind == 'application':
			projects = Project.objects.filter(application_identifier=identifier)
			selection = identifier
		elif kind == 'project':
			projects = [Project.objects.get(id=identifier)]
			selection = projects[0].name
		elif kind == 'account':
			account = Account.objects.get(id=identifier)
			projects = Project.objects.filter(account=account)
			selection = account.name
	except:
		pass
	dictionary = {
		'accounts_and_applications': set(Account.objects.all()) | set(Project.objects.all()) | set(get_project_applications()),
		'area_access': AreaAccessRecord.objects.filter(project__in=projects, end__gt=start_date, end__lte=end_date) if projects else None,
		'consumables': ConsumableWithdraw.objects.filter(project__in=projects, date__gt=start_date, date__lte=end_date) if projects else None,
		'missed_reservations': Reservation.objects.filter(project__in=projects, missed=True, end__gt=start_date, end__lte=end_date) if projects else None,
		'staff_charges': StaffCharge.objects.filter(project__in=projects, end__gt=start_date, end__lte=end_date) if projects else None,
		'training_sessions': TrainingSession.objects.filter(project__in=projects, date__gt=start_date, date__lte=end_date) if projects else None,
		'usage_events': UsageEvent.objects.filter(project__in=projects, end__gt=start_date, end__lte=end_date) if projects else None,
		'project_autocomplete': True,
		'selection': selection
	}
	dictionary['no_charges'] = not (dictionary['area_access'] or dictionary['consumables'] or dictionary['missed_reservations'] or dictionary['staff_charges'] or dictionary['training_sessions'] or dictionary['usage_events'])
	return render(request, 'usage/usage.html', {**base_dictionary, **dictionary})


@staff_member_required(login_url=None)
@require_GET
def project_billing(request, kind=None, identifier=None):
	base_dictionary, start_date, end_date = date_parameters_dictionary(request)
	base_dictionary['project_autocomplete'] = True
	base_dictionary['accounts_and_applications'] = set(Account.objects.all()) | set(Project.objects.all()) | set(get_project_applications())

	project_id = None
	formatted_applications = None
	selection = ''
	try:
		if kind == 'application':
			formatted_applications = identifier
			selection = identifier
		elif kind == 'project':
			projects = [Project.objects.get(id=identifier)]
			formatted_applications = projects[0].application_identifier
			project_id = identifier
			selection = projects[0].name
		elif kind == 'account':
			account = Account.objects.get(id=identifier)
			projects = Project.objects.filter(account=account, active=True, account__active=True)
			formatted_applications = ','.join(
				map(str, set(projects.values_list('application_identifier', flat=True)))) if projects else None
			selection = account.name

		base_dictionary['selection'] = selection
		billing_dictionary = billing_dict(start_date, end_date, None, formatted_applications, project_id, force_pi=True)
		return render(request, 'usage/billing.html', {**base_dictionary, **billing_dictionary})
	except Exception as e:
		logger.warning(str(e))
		return render(request, 'usage/billing.html', base_dictionary)


def is_user_pi(user, application_pi_row):
	return application_pi_row is not None and (user.username == application_pi_row['username'] or (user.first_name == application_pi_row['first_name'] and user.last_name == application_pi_row['last_name']))


def billing_dict(start_date, end_date, user, formatted_applications, project_id=None, force_pi=None):
	dictionary = {}

	cost_activity_url = settings.BILLING_SERVICE['cost_activity_url']
	project_lead_url = settings.BILLING_SERVICE['project_lead_url']
	keyword_arguments = settings.BILLING_SERVICE['keyword_arguments']

	cost_activity_params = {
		'created_date_gte': f"'{start_date.strftime('%m/%d/%Y')}'",
		'created_date_lt': f"'{end_date.strftime('%m/%d/%Y')}'",
		'application_names': f"'{formatted_applications}'",
		'$format': 'json'
	}
	cost_activity_response = get(cost_activity_url, params=cost_activity_params, **keyword_arguments)
	cost_activity_data = cost_activity_response.json()['d']

	if force_pi is None:
		latest_pis_params = {'$format': 'json'}
		latest_pis_response = get(project_lead_url, params=latest_pis_params, **keyword_arguments)
		latest_pis_data = latest_pis_response.json()['d']

	project_totals = {}
	application_totals = {}
	user_pi_applications = list()
	# Construct a tree of account, application, project, and member total spending
	cost_activities_tree = {}
	for activity in cost_activity_data:
		if project_id and activity['project_id'] != project_id:
			continue
		project_totals.setdefault(activity['project_id'], 0)
		application_totals.setdefault(activity['application_id'], 0)
		account_key = (activity['account_id'], activity['account_name'])
		application_key = (activity['application_id'], activity['application_name'])
		project_key = (activity['project_id'], activity['project_name'])
		user_key = (activity['member_id'], User.objects.filter(id__in=[activity['member_id']]).first())
		user_is_pi = is_user_pi(user, next((x for x in latest_pis_data if x['application_name'] == activity['application_name']), None)) if force_pi is None else True
		if user_is_pi:
			user_pi_applications.append(activity['application_id'])
		if user_is_pi or str(user.id) == activity['member_id']:
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
	} if cost_activities_tree else {'activities': {}}
	return dictionary
