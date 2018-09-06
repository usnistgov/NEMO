import psycopg2
from django.conf import settings
from NEMO.models import User


def get_usage_from_billing(user, start, end):
	billing_connection = psycopg2.connect(settings.BILLING_SERVICE_POSTGRES_CONNECTION)
	cursor = billing_connection.cursor()
	formatted_start = start.strftime('%m/%d/%Y')
	formatted_end = end.strftime('%m/%d/%Y')
	formatted_projects = ','.join(map(str, set(user.active_projects().values_list('application_identifier', flat=True))))
	cursor.execute(f"select * from ( exec \"cost_activity_account_application_project_daterange_view\".\"getCostActivityFullViewByDateRange\"(\'{formatted_start}\',\'{formatted_end}\',\'{formatted_projects}\')) AS result")
	cost_activity_rows = dict_fetch_all(cursor)
	cursor.execute("select * from application_latest_pis_view")
	pi_rows = dict_fetch_all(cursor)
	cursor.close()
	billing_connection.close()

	project_totals = {}
	application_totals = {}
	user_pi_applications = list()
	# construct tree of account, application, project, and member total spending
	cost_activities_tree = {}
	for activity in cost_activity_rows:
		project_totals.setdefault(activity['project_id'], 0)
		application_totals.setdefault(activity['application_id'], 0)
		account_key = (activity['account_id'], activity['account_name'])
		application_key = (activity['application_id'], activity['application_name'])
		project_key = (activity['project_id'], activity['project_name'])
		user_key = (activity['member_id'], User.objects.get(pk=activity['member_id']))
		user_is_pi = is_user_pi(user, next(
			(x for x in pi_rows if x['application_name'] == activity['application_name']), None))
		if user_is_pi:
			user_pi_applications.append(activity['application_id'])
		if user_is_pi or user.id == activity['member_id']:
			cost_activities_tree.setdefault((activity['account_id'], activity['account_name']), {})
			cost_activities_tree[account_key].setdefault(application_key, {})
			cost_activities_tree[account_key][application_key].setdefault(project_key, {})
			cost_activities_tree[account_key][application_key][project_key].setdefault(user_key, 0)
			cost = - activity['cost'] if activity['activity_type'] == 'refund_activity' else activity['cost']
			cost_activities_tree[account_key][application_key][project_key][user_key] = cost_activities_tree[account_key][application_key][project_key][user_key] + cost
			project_totals[activity['project_id']] = project_totals[activity['project_id']] + cost
			application_totals[activity['application_id']] = application_totals[activity['application_id']] + cost

	return {'activities': cost_activities_tree,
			'project_totals': project_totals,
			'application_totals': application_totals,
			'user_pi_applications': user_pi_applications} if cost_activities_tree else {}


def dict_fetch_all(cursor):
	"""Return all rows from a cursor as a dict"""
	columns = [col[0] for col in cursor.description]
	return [
		dict(zip(columns, row))
		for row in cursor.fetchall()
	]


def is_user_pi(user, application_pi_row):
	return application_pi_row is not None and (user.username == application_pi_row['username'] or (user.first_name == application_pi_row['first_name'] and user.last_name == application_pi_row['last_name']))
