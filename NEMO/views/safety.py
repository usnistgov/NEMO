from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.template import Context, Template
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods

from NEMO.forms import SafetyIssueCreationForm, SafetyIssueUpdateForm
from NEMO.models import SafetyIssue
from NEMO.utilities import send_mail, EmailCategory
from NEMO.views.customization import get_customization, get_media_file_contents
from NEMO.views.notifications import create_safety_notification, delete_safety_notification, get_notifications


@login_required
@require_http_methods(['GET', 'POST'])
def safety(request):
	dictionary = {}
	if request.method == 'POST':
		form = SafetyIssueCreationForm(request.user, data=request.POST)
		if form.is_valid():
			issue = form.save()
			send_safety_email_notification(request, issue)
			dictionary['title'] = 'Concern received'
			dictionary['heading'] = 'Your safety concern was sent to the staff and will be addressed promptly'
			create_safety_notification(issue)
			return render(request, 'acknowledgement.html', dictionary)
	tickets = SafetyIssue.objects.filter(resolved=False).order_by('-creation_time')
	if not request.user.is_staff:
		tickets = tickets.filter(visible=True)
	dictionary['tickets'] = tickets
	dictionary['safety_introduction'] = get_media_file_contents('safety_introduction.html')
	dictionary['notifications'] = get_notifications(request.user, SafetyIssue)
	return render(request, 'safety/safety.html', dictionary)


def send_safety_email_notification(request, issue):
	recipient = get_customization('safety_email_address')
	message = get_media_file_contents('safety_issue_email.html')
	if recipient and message:
		subject = 'Safety issue'
		dictionary = {
			'issue': issue,
			'issue_absolute_url': request.build_absolute_uri(issue.get_absolute_url()),
		}
		rendered_message = Template(message).render(Context(dictionary))
		from_email = issue.reporter.email if issue.reporter else recipient
		send_mail(subject=subject, content=rendered_message, from_email=from_email, to=[recipient], email_category=EmailCategory.SAFETY)


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
			issue = form.save()
			if issue.resolved:
				delete_safety_notification(issue)
			return HttpResponseRedirect(reverse('safety'))
	dictionary = {
		'ticket': get_object_or_404(SafetyIssue, id=ticket_id)
	}
	return render(request, 'safety/update_issue.html', dictionary)
