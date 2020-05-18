from django.contrib.admin.views.decorators import staff_member_required
from django.core.files.storage import get_storage_class
from django.core.validators import validate_email
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

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


customizable_key_values = [
	'feedback_email_address',
	'user_office_email_address',
	'safety_email_address',
	'abuse_email_address',
	'self_log_in',
	'self_log_out',
	'calendar_view',
	'calendar_first_day_of_week',
	'calendar_date_format'
	]

customizable_content = [
	('login_banner', '.html'),
	('safety_introduction', '.html'),
	('nanofab_rules_tutorial', '.html'),
	('authorization_failed', '.html'),
	('cancellation_email', '.html'),
	('feedback_email', '.html'),
	('generic_email', '.html'),
	('missed_reservation_email', '.html'),
	('nanofab_rules_tutorial_email', '.html'),
	('new_task_email', '.html'),
	('reservation_reminder_email', '.html'),
	('reservation_warning_email', '.html'),
	('safety_issue_email', '.html'),
	('staff_charge_reminder_email', '.html'),
	('task_status_notification', '.html'),
	('unauthorized_tool_access_email', '.html'),
	('usage_reminder_email', '.html'),
	('reservation_cancelled_user_email', '.html'),
	('reservation_created_user_email', '.html'),
	('rates', '.json'),
	('jumbotron_watermark', '.png'),
]


def get_customization(name):
	if name not in customizable_key_values:
		raise Exception('Invalid customization')
	try:
		return Customization.objects.get(name=name).value
	except Customization.DoesNotExist:
		return ''


def set_customization(name, value):
	if name not in customizable_key_values:
		raise Exception(f'Invalid customization: {value}')
	if value:
		if name in ['feedback_email_address', 'user_office_email_address', 'safety_email_address', 'abuse_email_address']:
			validate_email(value)
		Customization.objects.update_or_create(name=name, defaults={'value': value})
	else:
		try:
			Customization.objects.get(name=name).delete()
		except Customization.DoesNotExist:
			pass


@staff_member_required(login_url=None)
@require_GET
def customization(request):
	dictionary = {name: get_media_file_contents(name + extension) for name, extension in customizable_content}
	dictionary.update({y: get_customization(y) for y in customizable_key_values})
	return render(request, 'customizations.html', dictionary)


@staff_member_required(login_url=None)
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
			rate_class.load_rates()
	elif element == 'email_addresses':
		set_customization('feedback_email_address', request.POST.get('feedback_email_address', ''))
		set_customization('safety_email_address', request.POST.get('safety_email_address', ''))
		set_customization('abuse_email_address', request.POST.get('abuse_email_address', ''))
		set_customization('user_office_email_address', request.POST.get('user_office_email_address', ''))
	elif element == 'application_settings':
		set_customization('self_log_in', request.POST.get('self_log_in', ''))
		set_customization('self_log_out', request.POST.get('self_log_out', ''))
	elif element == 'calendar_settings':
		set_customization('calendar_view', request.POST.get('calendar_view', ''))
		set_customization('calendar_first_day_of_week', request.POST.get('calendar_first_day_of_week', ''))
		set_customization('calendar_date_format', request.POST.get('calendar_date_format', ''))
	else:
		return HttpResponseBadRequest('Invalid customization')
	return redirect('customization')
