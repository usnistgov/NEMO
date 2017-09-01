from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.http import HttpResponseRedirect
from django.shortcuts import render, get_object_or_404
from django.template import Template, Context
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_GET

from NEMO.forms import SafetyIssueCreationForm, SafetyIssueUpdateForm
from NEMO.models import SafetyIssue
from NEMO.views.customization import get_media_file_contents, get_customization


@login_required
@require_http_methods(['GET', 'POST'])
def safety(request):
	if request.method == 'POST':
		form = SafetyIssueCreationForm(request.user, data=request.POST)
		if form.is_valid():
			issue = form.save()
			send_safety_email_notification(request, issue)
			dictionary = {
				'title': 'Concern received',
				'heading': 'Your safety concern was sent to NanoFab staff and will be addressed promptly',
			}
			return render(request, 'acknowledgement.html', dictionary)
	tickets = SafetyIssue.objects.filter(resolved=False).order_by('-creation_time')
	if not request.user.is_staff:
		tickets = tickets.filter(visible=True)
	safety_introduction = get_media_file_contents('safety_introduction.html')
	return render(request, 'safety/safety.html', {'tickets': tickets, 'safety_introduction': safety_introduction})


def send_safety_email_notification(request, issue):
	subject = 'Safety issue'
	dictionary = {
		'issue': issue,
		'issue_absolute_url': request.build_absolute_uri(issue.get_absolute_url()),
	}
	recipient = get_customization('safety_email_address')
	message = get_media_file_contents('safety_issue_email.html')
	if not recipient or not message:
		return
	rendered_message = Template(message).render(Context(dictionary))
	from_email = issue.reporter.email if issue.reporter else recipient
	send_mail(subject, '', from_email, [recipient], html_message=rendered_message)


@login_required
@require_GET
def resolved_safety_issues(request):
	tickets = SafetyIssue.objects.filter(resolved=True)
	if not request.user.is_staff:
		tickets = tickets.filter(visible=True)
	return render(request, 'safety/resolved_issues.html', {'tickets': tickets})


@staff_member_required(login_url=None)
@require_http_methods(['GET', 'POST'])
def update_safety_issue(request, ticket_id):
	if request.method == 'POST':
		ticket = get_object_or_404(SafetyIssue, id=ticket_id)
		form = SafetyIssueUpdateForm(request.user, data=request.POST, instance=ticket)
		if form.is_valid():
			form.save()
			return HttpResponseRedirect(reverse('safety'))
	dictionary = {
		'ticket': get_object_or_404(SafetyIssue, id=ticket_id)
	}
	return render(request, 'safety/update_issue.html', dictionary)
