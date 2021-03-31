from datetime import datetime
from logging import getLogger
from typing import List, Set

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_GET
from requests import get

from NEMO.models import AreaAccessRecord, ConsumableWithdraw, Reservation, StaffCharge, TrainingSession, UsageEvent, User, Project, Account
from NEMO.utilities import get_month_timeframe, month_list, parse_start_and_end_date, BasicDisplayTable
from NEMO.views.api_billing import (
	BillableItem,
	billable_items_usage_events,
	billable_items_area_access_records,
	billable_items_missed_reservations,
	billable_items_staff_charges,
	billable_items_consumable_withdrawals,
	billable_items_training_sessions
)

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
	if request.GET.get('start_date') and request.GET.get('end_date'):
		start_date, end_date = parse_start_and_end_date(request.GET.get('start_date'), request.GET.get('end_date'))
	else:
		start_date, end_date = get_month_timeframe()
	kind = request.GET.get("type")
	identifier = request.GET.get("id")
	dictionary = {
		'month_list': month_list(),
		'start_date': start_date,
		'end_date': end_date,
		'kind': kind,
		'identifier': identifier,
		'tab_url': get_url_for_other_tab(request),
		'billing_service': get_billing_service().get('available', False),
	}
	return dictionary, start_date, end_date, kind, identifier


@login_required
@require_GET
def usage(request):
	user: User = request.user
	user_managed_projects = get_managed_projects(user)
	base_dictionary, start_date, end_date, kind, identifier = date_parameters_dictionary(request)
	customer_filter = Q(customer=user) | Q(project__in=user_managed_projects)
	user_filter = Q(user=user) | Q(project__in=user_managed_projects)
	trainee_filter = Q(trainee=user) | Q(project__in=user_managed_projects)
	project_id = request.GET.get("pi_project")
	csv_export = bool(request.GET.get("csv", False))
	if user_managed_projects:
		base_dictionary['selected_project'] = "all"
	if project_id:
		project = get_object_or_404(Project, id=project_id)
		base_dictionary['selected_project'] = project
		customer_filter = customer_filter & Q(project=project)
		user_filter = user_filter & Q(project=project)
		trainee_filter = trainee_filter & Q(project=project)
	area_access = AreaAccessRecord.objects.filter(customer_filter).filter(end__gt=start_date, end__lte=end_date).order_by('-start')
	consumables = ConsumableWithdraw.objects.filter(customer_filter).filter(date__gt=start_date, date__lte=end_date)
	missed_reservations = Reservation.objects.filter(user_filter).filter(missed=True, end__gt=start_date, end__lte=end_date)
	staff_charges = StaffCharge.objects.filter(customer_filter).filter(end__gt=start_date, end__lte=end_date)
	training_sessions = TrainingSession.objects.filter(trainee_filter).filter(date__gt=start_date, date__lte=end_date)
	usage_events = UsageEvent.objects.filter(user_filter).filter(end__gt=start_date, end__lte=end_date)
	if csv_export:
		return csv_export_response(usage_events, area_access, training_sessions, staff_charges, consumables, missed_reservations)
	else:
		dictionary = {
			'area_access': area_access,
			'consumables': consumables,
			'missed_reservations': missed_reservations,
			'staff_charges': staff_charges,
			'training_sessions': training_sessions,
			'usage_events': usage_events,
			'can_export': True,
		}
		if user_managed_projects:
			dictionary['pi_projects'] = user_managed_projects
		dictionary['no_charges'] = not (dictionary['area_access'] or dictionary['consumables'] or dictionary['missed_reservations'] or dictionary['staff_charges'] or dictionary['training_sessions'] or dictionary['usage_events'])
		return render(request, 'usage/usage.html', {**base_dictionary, **dictionary})


@login_required
@require_GET
def billing(request):
	user: User = request.user
	base_dictionary, start_date, end_date, kind, identifier = date_parameters_dictionary(request)
	if not base_dictionary['billing_service']:
		return redirect('usage')
	user_project_applications = list(user.active_projects().values_list('application_identifier', flat=True)) + list(user.managed_projects.values_list('application_identifier', flat=True))
	formatted_applications = ','.join(map(str, set(user_project_applications)))
	try:
		billing_dictionary = billing_dict(start_date, end_date, user, formatted_applications)
		return render(request, 'usage/billing.html', {**base_dictionary, **billing_dictionary})
	except Exception as e:
		logger.warning(str(e))
		return render(request, 'usage/billing.html', base_dictionary)


@staff_member_required(login_url=None)
@require_GET
def project_usage(request):
	base_dictionary, start_date, end_date, kind, identifier = date_parameters_dictionary(request)

	area_access, consumables, missed_reservations, staff_charges, training_sessions, usage_events = None, None, None, None, None, None

	projects = []
	user = None
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
		elif kind == 'user':
			user = User.objects.get(id=identifier)
			projects = user.active_projects()
			selection = str(user)

		if projects:
			area_access = AreaAccessRecord.objects.filter(project__in=projects, end__gt=start_date, end__lte=end_date).order_by('-start')
			consumables = ConsumableWithdraw.objects.filter(project__in=projects, date__gt=start_date, date__lte=end_date)
			missed_reservations = Reservation.objects.filter(project__in=projects, missed=True, end__gt=start_date, end__lte=end_date)
			staff_charges = StaffCharge.objects.filter(project__in=projects, end__gt=start_date, end__lte=end_date)
			training_sessions = TrainingSession.objects.filter(project__in=projects, date__gt=start_date, date__lte=end_date)
			usage_events = UsageEvent.objects.filter(project__in=projects, end__gt=start_date, end__lte=end_date)
			if user:
				area_access = area_access.filter(customer=user)
				consumables = consumables.filter(customer=user)
				missed_reservations = missed_reservations.filter(user=user)
				staff_charges = staff_charges.filter(customer=user)
				training_sessions = training_sessions.filter(trainee=user)
				usage_events = usage_events.filter(user=user)
			if bool(request.GET.get("csv", False)):
				return csv_export_response(usage_events, area_access, training_sessions, staff_charges, consumables, missed_reservations)
	except:
		pass
	dictionary = {
		'search_items': set(Account.objects.all()) | set(Project.objects.all()) | set(get_project_applications()) | set(User.objects.filter(is_active=True)),
		'area_access': area_access,
		'consumables': consumables,
		'missed_reservations': missed_reservations,
		'staff_charges': staff_charges,
		'training_sessions': training_sessions,
		'usage_events': usage_events,
		'project_autocomplete': True,
		'selection': selection,
		'can_export': True,
	}
	dictionary['no_charges'] = not (dictionary['area_access'] or dictionary['consumables'] or dictionary['missed_reservations'] or dictionary['staff_charges'] or dictionary['training_sessions'] or dictionary['usage_events'])
	return render(request, 'usage/usage.html', {**base_dictionary, **dictionary})


@staff_member_required(login_url=None)
@require_GET
def project_billing(request):
	base_dictionary, start_date, end_date, kind, identifier = date_parameters_dictionary(request)
	if not base_dictionary['billing_service']:
		return redirect('project_usage')
	base_dictionary['project_autocomplete'] = True
	base_dictionary['search_items'] = set(Account.objects.all()) | set(Project.objects.all()) | set(get_project_applications()) | set(User.objects.filter(is_active=True))

	project_id = None
	account_id = None
	user = None
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
			formatted_applications = ','.join(map(str, set(projects.values_list('application_identifier', flat=True)))) if projects else None
			account_id = account.id
			selection = account.name
		elif kind == 'user':
			user = User.objects.get(id=identifier)
			projects = user.active_projects()
			formatted_applications = ','.join(map(str, set(projects.values_list('application_identifier', flat=True)))) if projects else None
			selection = str(user)

		base_dictionary['selection'] = selection
		billing_dictionary = billing_dict(start_date, end_date, user, formatted_applications, project_id, account_id=account_id, force_pi=True if not user else False)
		return render(request, 'usage/billing.html', {**base_dictionary, **billing_dictionary})
	except Exception as e:
		logger.warning(str(e))
		return render(request, 'usage/billing.html', base_dictionary)


def is_user_pi(user: User, latest_pis_data, activity, user_managed_applications: List[str]):
	# Check if the user is set as a PI in NEMO, otherwise check from latest_pis_data
	application = activity['application_name']
	if application in user_managed_applications:
		return True
	else:
		application_pi_row = next((x for x in latest_pis_data if x['application_name'] == application), None)
		return application_pi_row is not None and (user.username == application_pi_row['username'] or (user.first_name == application_pi_row['first_name'] and user.last_name == application_pi_row['last_name']))


def billing_dict(start_date, end_date, user, formatted_applications, project_id=None, account_id=None, force_pi=False):
	# The parameter force_pi allows us to display information as if the user was the project pi
	# This is useful on the admin project billing page tp display other project users for example
	dictionary = {}

	billing_service = get_billing_service()
	if not billing_service.get('available', False):
		return dictionary

	cost_activity_url = billing_service['cost_activity_url']
	project_lead_url = billing_service['project_lead_url']
	keyword_arguments = billing_service['keyword_arguments']

	cost_activity_params = {
		'created_date_gte': f"'{start_date.strftime('%m/%d/%Y')}'",
		'created_date_lt': f"'{end_date.strftime('%m/%d/%Y')}'",
		'application_names': f"'{formatted_applications}'",
		'$format': 'json'
	}
	cost_activity_response = get(cost_activity_url, params=cost_activity_params, **keyword_arguments)
	cost_activity_data = cost_activity_response.json()['d']

	if not force_pi:
		latest_pis_params = {'$format': 'json'}
		latest_pis_response = get(project_lead_url, params=latest_pis_params, **keyword_arguments)
		latest_pis_data = latest_pis_response.json()['d']

	project_totals = {}
	application_totals = {}
	account_totals = {}
	user_pi_applications = list()
	# Construct a tree of account, application, project, and member total spending
	cost_activities_tree = {}
	user_managed_applications = [project.application_identifier for project in user.managed_projects.all()]
	for activity in cost_activity_data:
		if (project_id and activity['project_id'] != str(project_id)) or (account_id and activity['account_id'] != str(account_id)):
			continue
		project_totals.setdefault(activity['project_id'], 0)
		application_totals.setdefault(activity['application_id'], 0)
		account_totals.setdefault(activity['account_id'], 0)
		account_key = (activity['account_id'], activity['account_name'])
		application_key = (activity['application_id'], activity['application_name'])
		project_key = (activity['project_id'], activity['project_name'])
		user_key = (activity['member_id'], User.objects.filter(id__in=[activity['member_id']]).first())
		user_is_pi = is_user_pi(user, latest_pis_data, activity, user_managed_applications) if not force_pi else True
		if user_is_pi:
			user_pi_applications.append(activity['application_id'])
		if user_is_pi or str(user.id) == activity['member_id']:
			cost_activities_tree.setdefault((activity['account_id'], activity['account_name']), {})
			cost_activities_tree[account_key].setdefault(application_key, {})
			cost_activities_tree[account_key][application_key].setdefault(project_key, {})
			cost_activities_tree[account_key][application_key][project_key].setdefault(user_key, 0)
			cost = 0
			if activity['cost'] is not None:
				cost = -activity['cost'] if activity['activity_type'] == 'refund_activity' else activity['cost']
			cost_activities_tree[account_key][application_key][project_key][user_key] = cost_activities_tree[account_key][application_key][project_key][user_key] + cost
			project_totals[activity['project_id']] = project_totals[activity['project_id']] + cost
			application_totals[activity['application_id']] = application_totals[activity['application_id']] + cost
			account_totals[activity['account_id']] = account_totals[activity['account_id']] + cost
	dictionary['spending'] = {
		'activities': cost_activities_tree,
		'project_totals': project_totals,
		'application_totals': application_totals,
		'account_totals': account_totals,
		'user_pi_applications': user_pi_applications
	} if cost_activities_tree else {'activities': {}}
	return dictionary


def csv_export_response(usage_events, area_access, training_sessions, staff_charges, consumables, missed_reservations):
	table_result = BasicDisplayTable()
	table_result.add_header(("type", "Type"))
	table_result.add_header(("user", "User"))
	table_result.add_header(("name", "Item"))
	table_result.add_header(("details", "Details"))
	table_result.add_header(("project", "Project"))
	table_result.add_header(("start", "Start time"))
	table_result.add_header(("end", "End time"))
	table_result.add_header(("quantity", "Quantity"))
	data: List[BillableItem] = []
	data.extend(billable_items_missed_reservations(missed_reservations))
	data.extend(billable_items_consumable_withdrawals(consumables))
	data.extend(billable_items_staff_charges(staff_charges))
	data.extend(billable_items_training_sessions(training_sessions))
	data.extend(billable_items_area_access_records(area_access))
	data.extend(billable_items_usage_events(usage_events))
	for billable_item in data:
		table_result.add_row(vars(billable_item))
	response = table_result.to_csv()
	filename = f"usage_export_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.csv"
	response["Content-Disposition"] = f'attachment; filename="{filename}"'
	return response


def get_managed_projects(user: User) -> Set[Project]:
	# This function will get managed projects from NEMO and also attempt to get them from billing service
	managed_projects = set(list(user.managed_projects.all()))
	billing_service = get_billing_service()
	if billing_service.get('available', False):
		# if we have a billing service, use it to determine project lead
		project_lead_url = billing_service['project_lead_url']
		keyword_arguments = billing_service['keyword_arguments']
		latest_pis_params = {'$format': 'json'}
		latest_pis_response = get(project_lead_url, params=latest_pis_params, **keyword_arguments)
		latest_pis_data = latest_pis_response.json()['d']
		for project_lead in latest_pis_data:
			if project_lead['username'] == user.username or (
					project_lead['first_name'] == user.first_name and project_lead['last_name'] == user.last_name):
				try:
					for managed_project in Project.objects.filter(application_identifier=project_lead['application_name']):
						managed_projects.add(managed_project)
				except Project.DoesNotExist:
					pass
	return managed_projects


def get_billing_service():
	return getattr(settings, 'BILLING_SERVICE', {})
