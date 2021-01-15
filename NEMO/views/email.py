from logging import getLogger
from smtplib import SMTPException

from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.core.validators import validate_email
from django.db.models import Q
from django.http import HttpResponseBadRequest, HttpResponse
from django.shortcuts import render, get_object_or_404
from django.template import Template, Context
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_GET, require_POST

from NEMO.forms import EmailBroadcastForm
from NEMO.models import Tool, Account, Project, User, Area
from NEMO.utilities import send_mail, EmailCategory
from NEMO.views.customization import get_media_file_contents, get_customization

logger = getLogger(__name__)


@login_required
@require_GET
def get_email_form(request):
	recipient = request.GET.get('recipient', '')
	try:
		validate_email(recipient)
	except:
		return HttpResponseBadRequest('Recipient not valid.')
	return render(request, 'email/email_form.html', {'recipient': recipient})


@login_required
@require_GET
def get_email_form_for_user(request, user_id):
	recipient = get_object_or_404(User, id=user_id)
	return render(request, 'email/email_form.html', {'name': recipient.get_full_name(), 'recipient': recipient.email})


@login_required
@require_POST
def send_email(request):
	try:
		recipient = request.POST['recipient']
		validate_email(recipient)
		recipient_list = [recipient]
	except:
		return HttpResponseBadRequest('The intended recipient was not a valid email address. The email was not sent.')
	sender = request.user.email
	subject = request.POST.get('subject')
	body = request.POST.get('body')
	if request.POST.get('copy_me'):
		recipient_list.append(sender)
	try:
		send_mail(subject=subject, content=body, from_email=sender, bcc=recipient_list, email_category=EmailCategory.DIRECT_CONTACT)
	except SMTPException as error:
		site_title = get_customization('site_title')
		error_message = f'{site_title} was unable to send the email through the email server. The error message that was received is: ' + str(error)
		logger.exception(error_message)
		dictionary = {
			'title': 'Email not sent',
			'heading': 'There was a problem sending your email',
			'content': error_message,
		}
		return render(request, 'acknowledgement.html', dictionary)
	dictionary = {
		'title': 'Email sent',
		'heading': 'Your email was sent',
	}
	return render(request, 'acknowledgement.html', dictionary)


@staff_member_required(login_url=None)
@require_GET
def email_broadcast(request, audience=''):
	dictionary = {}
	if audience == 'tool':
		dictionary['search_base'] = Tool.objects.filter(visible=True)
	elif audience == 'area':
		dictionary['search_base'] = Area.objects.all()
	elif audience == 'project':
		dictionary['search_base'] = Project.objects.filter(active=True, account__active=True)
	elif audience == 'account':
		dictionary['search_base'] = Account.objects.filter(active=True)
	dictionary['audience'] = audience
	return render(request, 'email/email_broadcast.html', dictionary)


@staff_member_required(login_url=None)
@require_GET
def compose_email(request):
	audience = request.GET.get('audience')
	selection = request.GET.get('selection')
	try:
		if audience == 'tool':
			users = User.objects.filter(qualifications__id=selection).distinct()
		elif audience == 'area':
			access_levels = Area.objects.get(pk=selection).get_physical_access_levels()
			user_filter = Q(physical_access_levels__in=access_levels)
			# if one of the access levels allows staff, add all staff
			if access_levels.filter(allow_staff_access=True).exists():
				user_filter = user_filter | Q(is_staff=True)
			users = User.objects.filter(user_filter).distinct()
		elif audience == 'project':
			users = User.objects.filter(projects__id=selection).distinct()
		elif audience == 'account':
			users = User.objects.filter(projects__account__id=selection).distinct()
		else:
			dictionary = {'error': 'You specified an invalid audience'}
			return render(request, 'email/email_broadcast.html', dictionary)
	except:
		dictionary = {'error': 'You specified an invalid audience parameter'}
		return render(request, 'email/email_broadcast.html', dictionary)
	generic_email_sample = get_media_file_contents('generic_email.html')
	dictionary = {
		'audience': audience,
		'selection': selection,
		'users': users,
	}
	if generic_email_sample:
		generic_email_context = {
			'title': 'TITLE',
			'greeting': 'Greeting',
			'contents': 'Contents',
			'template_color': '#5bc0de',
		}
		dictionary['generic_email_sample'] = Template(generic_email_sample).render(Context(generic_email_context))
	return render(request, 'email/compose_email.html', dictionary)


@staff_member_required(login_url=None)
@require_POST
def send_broadcast_email(request):
	content = get_media_file_contents('generic_email.html')
	if not content:
		return HttpResponseBadRequest('Generic email template not defined. Visit the customization page to upload a template.')
	form = EmailBroadcastForm(request.POST)
	if not form.is_valid():
		return render(request, 'email/compose_email.html', {'form': form})
	dictionary = {
		'title': form.cleaned_data['title'],
		'greeting': form.cleaned_data['greeting'],
		'contents': form.cleaned_data['contents'],
		'template_color': form.cleaned_data['color'],
	}
	content = Template(content).render(Context(dictionary))
	users = None
	audience = form.cleaned_data['audience']
	selection = form.cleaned_data['selection']
	active_choice = form.cleaned_data['only_active_users']
	try:
		if audience == 'tool':
			users = User.objects.filter(qualifications__id=selection)
		elif audience == 'project':
			users = User.objects.filter(projects__id=selection)
		elif audience == 'account':
			users = User.objects.filter(projects__account__id=selection)
		if active_choice:
			users = users.filter(is_active=True)
	except Exception as error:
		warning_message = 'Your email was not sent. There was a problem finding the users to send the email to.'
		dictionary = {'error': warning_message}
		logger.warning(warning_message + ' audience: {}, only_active: {}. The error message that was received is: {}'.format(audience, active_choice, str(error)))
		return render(request, 'email/compose_email.html', dictionary)
	if not users:
		dictionary = {'error': 'The audience you specified is empty. You must send the email to at least one person.'}
		return render(request, 'email/compose_email.html', dictionary)
	subject = form.cleaned_data['subject']
	users = [x.email for x in users]
	if form.cleaned_data['copy_me']:
		users += [request.user.email]
	try:
		send_mail(subject=subject, content=content, from_email=request.user.email, bcc=set(users), email_category=EmailCategory.BROADCAST_EMAIL)
	except SMTPException as error:
		site_title = get_customization('site_title')
		error_message = f"{site_title} was unable to send the email through the email server. The error message that was received is: " + str(error)
		logger.exception(error_message)
		dictionary = {
			'title': 'Email not sent',
			'heading': 'There was a problem sending your email',
			'content': error_message,
		}
		return render(request, 'acknowledgement.html', dictionary)
	dictionary = {
		'title': 'Email sent',
		'heading': 'Your email was sent',
	}
	return render(request, 'acknowledgement.html', dictionary)


@staff_member_required(login_url=None)
@require_POST
def email_preview(request):
	generic_email_template = get_media_file_contents('generic_email.html')
	if generic_email_template:
		form = EmailBroadcastForm(request.POST)
		email_context = {
			'title': form.data['title'],
			'greeting': form.data['greeting'],
			'contents': form.data['contents'],
			'template_color': form.data['color'],
		}
		email_content = Template(generic_email_template).render(Context(email_context))
		return HttpResponse(mark_safe(email_content))
	return HttpResponse()
