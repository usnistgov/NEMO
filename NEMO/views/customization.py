from django.core.files.storage import get_storage_class
from django.core.validators import validate_email
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from NEMO import init_admin_site
from NEMO.decorators import administrator_required
from NEMO.exceptions import InvalidCustomizationException
from NEMO.models import Customization


def get_media_file_contents(file_name):
	""" Get the contents of a media file if it exists. Return a blank string if it does not exist. """
	storage = get_storage_class()()
	if not storage.exists(file_name):
		return ''
	f = storage.open(file_name)
	try:
		return f.read().decode().strip()
	except UnicodeDecodeError:
		f = storage.open(file_name)
		return f.read()


def store_media_file(content, file_name):
	""" Delete any existing media file with the same name and save the new content into file_name in the media directory. If content is blank then no new file is created. """
	storage = get_storage_class()()
	storage.delete(file_name)
	if content:
		storage.save(file_name, content)


# Dictionary of customizable keys with default value
customizable_key_values = {
	'feedback_email_address': '',
	'user_office_email_address': '',
	'safety_email_address': '',
	'abuse_email_address': '',
	'facility_name': 'NanoFab',
	'site_title': 'NEMO',
	'self_log_in': '',
	'self_log_out': '',
	'calendar_login_logout': '',
	'dashboard_display_not_qualified_areas': '',
	'dashboard_staff_status_first_day_of_week': '1',
	'dashboard_staff_status_staff_only': '',
	'dashboard_staff_status_weekdays_only': '',
	'dashboard_staff_status_date_format': 'D m/d',
	'dashboard_staff_status_check_past_status': '',
	'dashboard_staff_status_check_future_status': '',
	'calendar_view': 'agendaWeek',
	'calendar_first_day_of_week': '1',
	'calendar_day_column_format': 'dddd MM/DD/YYYY',
	'calendar_week_column_format': 'ddd M/DD',
	'calendar_month_column_format': 'ddd',
	'calendar_start_of_the_day': '07:00:00',
	'calendar_now_indicator': '',
	'calendar_display_not_qualified_areas': '',
	'calendar_all_tools': '',
	'calendar_all_areas': '',
	'calendar_all_areastools': '',
	'calendar_outage_recurrence_limit': '90',
	'project_selection_template': '{{ project.name }}',
	'allow_bypass_interlock_on_failure': '',
	'tool_interlock_failure_message': 'Communication with the interlock failed',
	'door_interlock_failure_message': 'Communication with the interlock failed',
	'buddy_requests_title': 'Buddy requests board',
	'buddy_board_description': '',
	'access_requests_title': 'Access requests',
	'access_requests_description': '',
	'access_requests_minimum_users': '2',
	'access_requests_display_max': '',
	'weekend_access_notification_emails': '',
	'weekend_access_notification_cutoff_hour': '',
	'weekend_access_notification_cutoff_day': '',
	'weekend_access_notification_last_sent': '',
}

customizable_content = [
	('access_request_notification_email', '.html'),
	('authorization_failed', '.html'),
	('cancellation_email', '.html'),
	('counter_threshold_reached_email', '.html'),
	('facility_rules_tutorial', '.html'),
	('facility_rules_tutorial_email', '.html'),
	('feedback_email', '.html'),
	('generic_email', '.html'),
	('login_banner', '.html'),
	('missed_reservation_email', '.html'),
	('new_task_email', '.html'),
	('out_of_time_reservation_email', '.html'),
	('reorder_supplies_reminder_email', '.html'),
	('reservation_cancelled_user_email', '.html'),
	('reservation_created_user_email', '.html'),
	('reservation_ending_reminder_email', '.html'),
	('reservation_reminder_email', '.html'),
	('reservation_warning_email', '.html'),
	('safety_introduction', '.html'),
	('safety_issue_email', '.html'),
	('staff_charge_reminder_email', '.html'),
	('task_status_notification', '.html'),
	('unauthorized_tool_access_email', '.html'),
	('usage_reminder_email', '.html'),
	('weekend_access_email', '.html'),
	('weekend_no_access_email', '.html'),
	('rates', '.json'),
	('jumbotron_watermark', '.png'),
]


def get_customization(name, raise_exception=True):
	if name not in customizable_key_values.keys():
		raise InvalidCustomizationException(name)
	default_value = customizable_key_values[name]
	try:
		return Customization.objects.get(name=name).value
	except Customization.DoesNotExist:
		# return default value
		return default_value
	except Exception:
		if raise_exception:
			raise
		else:
			return default_value


def set_customization(name, value):
	if name not in customizable_key_values.keys():
		raise InvalidCustomizationException(name, value)
	if value:
		if name in ['feedback_email_address', 'user_office_email_address', 'safety_email_address', 'abuse_email_address']:
			validate_email(value)
		Customization.objects.update_or_create(name=name, defaults={'value': value})
	else:
		try:
			Customization.objects.get(name=name).delete()
		except Customization.DoesNotExist:
			pass


@administrator_required
@require_GET
def customization(request):
	dictionary = {name: get_media_file_contents(name + extension) for name, extension in customizable_content}
	dictionary.update({name: get_customization(name) for name in customizable_key_values.keys()})
	return render(request, 'customizations/customizations.html', dictionary)


@administrator_required
@require_POST
def customize(request, element):
	item = None
	for name, extension in customizable_content:
		if name == element:
			item = (name, extension)
			break
	if item:
		store_media_file(request.FILES.get(element, ''), item[0] + item[1])
		if item[0] == 'rates':
			from NEMO.rates import rate_class
			rate_class.load_rates(force_reload=True)
	elif element == 'email_addresses':
		set_customization('feedback_email_address', request.POST.get('feedback_email_address', ''))
		set_customization('safety_email_address', request.POST.get('safety_email_address', ''))
		set_customization('abuse_email_address', request.POST.get('abuse_email_address', ''))
		set_customization('user_office_email_address', request.POST.get('user_office_email_address', ''))
	elif element == 'application_settings':
		set_customization('self_log_in', request.POST.get('self_log_in', ''))
		set_customization('self_log_out', request.POST.get('self_log_out', ''))
		set_customization('calendar_login_logout', request.POST.get('calendar_login_logout', ''))
		set_customization('facility_name', request.POST.get('facility_name', ''))
		set_customization('site_title', request.POST.get('site_title', ''))
		set_customization('project_selection_template', request.POST.get('project_selection_template', ''))
		init_admin_site()
	elif element == 'calendar_settings':
		set_customization('calendar_view', request.POST.get('calendar_view', ''))
		set_customization('calendar_first_day_of_week', request.POST.get('calendar_first_day_of_week', ''))
		set_customization('calendar_start_of_the_day', request.POST.get('calendar_start_of_the_day', ''))
		set_customization('calendar_now_indicator', request.POST.get('calendar_now_indicator', ''))
		set_customization('calendar_day_column_format', request.POST.get('calendar_day_column_format', ''))
		set_customization('calendar_week_column_format', request.POST.get('calendar_week_column_format', ''))
		set_customization('calendar_month_column_format', request.POST.get('calendar_month_column_format', ''))
		set_customization('calendar_all_tools', request.POST.get('calendar_all_tools', ''))
		set_customization('calendar_all_areas', request.POST.get('calendar_all_areas', ''))
		set_customization('calendar_all_areastools', request.POST.get('calendar_all_areastools', ''))
		set_customization('calendar_outage_recurrence_limit', request.POST.get('calendar_outage_recurrence_limit', '90'))
	elif element == 'dashboard_settings':
		set_customization('dashboard_display_not_qualified_areas', request.POST.get('dashboard_display_not_qualified_areas', ''))
		set_customization('dashboard_staff_status_first_day_of_week', request.POST.get('dashboard_staff_status_first_day_of_week', ''))
		set_customization('dashboard_staff_status_staff_only', request.POST.get('dashboard_staff_status_staff_only', ''))
		set_customization('dashboard_staff_status_weekdays_only', request.POST.get('dashboard_staff_status_weekdays_only', ''))
		set_customization('dashboard_staff_status_date_format', request.POST.get('dashboard_staff_status_date_format', ''))
		set_customization('dashboard_staff_status_check_past_status', request.POST.get('dashboard_staff_status_check_past_status', ''))
		set_customization('dashboard_staff_status_check_future_status', request.POST.get('dashboard_staff_status_check_future_status', ''))
	elif element == 'interlock_settings':
		set_customization('allow_bypass_interlock_on_failure', request.POST.get('allow_bypass_interlock_on_failure', ''))
		set_customization('tool_interlock_failure_message', request.POST.get('tool_interlock_failure_message', ''))
		set_customization('door_interlock_failure_message', request.POST.get('door_interlock_failure_message', ''))
	elif element == 'requests_settings':
		set_customization('buddy_requests_title', request.POST.get('buddy_requests_title', ''))
		set_customization('buddy_board_description', request.POST.get('buddy_board_description', ''))
		set_customization('access_requests_title', request.POST.get('access_requests_title', ''))
		set_customization('access_requests_description', request.POST.get('access_requests_description', ''))
		set_customization('access_requests_minimum_users', request.POST.get('access_requests_minimum_users', ''))
		set_customization('access_requests_display_max', request.POST.get('access_requests_display_max', ''))
		set_customization('weekend_access_notification_emails', request.POST.get('weekend_access_notification_emails', ''))
		set_customization('weekend_access_notification_cutoff_hour', request.POST.get('weekend_access_notification_cutoff_hour', ''))
		set_customization('weekend_access_notification_cutoff_day', request.POST.get('weekend_access_notification_cutoff_day', ''))
	else:
		return HttpResponseBadRequest('Invalid customization')
	return redirect('customization')
