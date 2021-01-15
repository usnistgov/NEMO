from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.template import Template, Context
from django.views.decorators.http import require_http_methods

from NEMO.utilities import parse_parameter_string, send_mail, EmailCategory
from NEMO.views.constants import FEEDBACK_MAXIMUM_LENGTH
from NEMO.views.customization import get_customization, get_media_file_contents


@login_required
@require_http_methods(['GET', 'POST'])
def feedback(request):
	recipient = get_customization('feedback_email_address')
	email_contents = get_media_file_contents('feedback_email.html')
	if not recipient or not email_contents:
		return render(request, 'feedback.html', {'customization_required': True})

	if request.method == 'GET':
		return render(request, 'feedback.html')
	contents = parse_parameter_string(request.POST, 'feedback', FEEDBACK_MAXIMUM_LENGTH)
	if contents == '':
		return render(request, 'feedback.html')
	dictionary = {
		'contents': contents,
		'user': request.user,
	}

	email = Template(email_contents).render(Context(dictionary))
	send_mail(subject='Feedback from ' + str(request.user), content=email, from_email=request.user.email, to=[recipient], email_category=EmailCategory.FEEDBACK)
	dictionary = {
		'title': 'Feedback',
		'heading': 'Thanks for your feedback!',
		'content': 'Your feedback has been sent to the staff. We will follow up with you as soon as we can.',
	}
	return render(request, 'acknowledgement.html', dictionary)
