from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.shortcuts import render
from django.template import Template, RequestContext, Context
from django.views.decorators.http import require_http_methods

from NEMO.models import User, Project
from NEMO.views.customization import get_customization, get_media_file_contents


@login_required
@require_http_methods(['GET', 'POST'])
def nanofab_rules(request):
	if request.method == 'GET':
		tutorial = get_media_file_contents('nanofab_rules_tutorial.html')
		if tutorial:
			dictionary = {
				'active_user_count': User.objects.filter(is_active=True).count(),
				'active_project_count': Project.objects.filter(active=True).count(),
			}
			tutorial = Template(tutorial).render(RequestContext(request, dictionary))
		return render(request, 'nanofab_rules.html', {'nanofab_rules_tutorial': tutorial})
	elif request.method == 'POST':
		summary = request.POST.get('making_reservations_summary', '').strip()[:3000]
		dictionary = {
			'user': request.user,
			'making_reservations_rule_summary': summary,
		}
		abuse_email = get_customization('abuse_email_address')
		email_contents = get_media_file_contents('nanofab_rules_tutorial_email.html')
		if abuse_email and email_contents:
			message = Template(email_contents, dictionary).render(Context(dictionary))
			send_mail('NanoFab rules tutorial', '', abuse_email, [abuse_email], html_message=message)
		dictionary = {
			'title': 'NanoFab rules tutorial',
			'heading': 'Tutorial complete!',
			'content': 'Tool usage and reservation privileges have been enabled on your user account.',
		}
		request.user.training_required = False
		request.user.save()
		return render(request, 'acknowledgement.html', dictionary)
