from django.contrib.admin.views.decorators import staff_member_required
from django.core.files.storage import get_storage_class
from django.core.validators import validate_email
from django.http import HttpResponseBadRequest
from django.shortcuts import render, redirect
from django.views.decorators.http import require_POST, require_GET

from NEMO.models import Customization


def get_media_file_contents(file_name):
	""" Get the contents of a media file if it exists. Return a blank string if it does not exist. """
	storage = get_storage_class()()
	if not storage.exists(file_name):
		return ''
	f = storage.open(file_name)
	return f.read().strip()


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
	'abuse_email_address'
]

customizable_content = [
	'login_banner',
	'safety_introduction',
	'nanofab_rules_tutorial',
	'cancellation_email',
	'feedback_email',
	'generic_email',
	'missed_reservation_email',
	'nanofab_rules_tutorial_email',
	'new_task_email',
	'reservation_reminder_email',
	'reservation_warning_email',
	'safety_issue_email',
	'staff_charge_reminder_email',
	'task_status_notification',
	'unauthorized_tool_access_email',
	'usage_reminder_email',
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
	dictionary = {x: get_media_file_contents(x + '.html') for x in customizable_content}
	dictionary.update({y: get_customization(y) for y in customizable_key_values})
	return render(request, 'customizations.html', dictionary)


@staff_member_required(login_url=None)
@require_POST
def customize(request, element):
	if element in customizable_content:
		store_media_file(request.FILES.get(element, ''), element + '.html')
	elif element == 'email_addresses':
		set_customization('feedback_email_address', request.POST.get('feedback_email_address', ''))
		set_customization('safety_email_address', request.POST.get('safety_email_address', ''))
		set_customization('abuse_email_address', request.POST.get('abuse_email_address', ''))
		set_customization('user_office_email_address', request.POST.get('user_office_email_address', ''))
	else:
		return HttpResponseBadRequest('Invalid customization')
	return redirect('customization')
