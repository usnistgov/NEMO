from django.core.mail import send_mail
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from NEMO.models import User, ForgotPasswordToken, UserAuth
from NEMO.views.customization import get_media_file_contents
from django.template import Template, Context

@require_http_methods(['GET'])
def forgot_password(request):
	return render(request, 'db_authentication/forgot_password.html', {})

@require_http_methods(['POST'])
def forgot_password_process(request):
	email = request.POST.get('email')
	subject = "NEMO Password Reset"
	link = ""
	try:
		user = User.objects.get(email=email)
		message = get_media_file_contents('forgot_password_email.html')
		token = ForgotPasswordToken.create(email)
		token.save()
		link = request.build_absolute_uri(reverse('password_reset_token', args=[token.hash]))
	except User.DoesNotExist:
		user = None
		message = get_media_file_contents('forgot_password_email_no_user.html')

	dictionary = {"link": link}
	rendered_message = Template(message).render(Context(dictionary))
	send_mail(subject, '', None, [email], html_message=rendered_message)

	return render(request, 'db_authentication/forgot_password_process.html', {'email': email})

@require_http_methods(['GET', 'POST'])
def password_reset_token(request, token):
	try:
		token = ForgotPasswordToken.objects.get(hash=token)
	except ForgotPasswordToken.DoesNotExist:
		token = None

	if request.method == 'GET':
		if token and token.is_valid():
			return render(request, 'db_authentication/password_reset_token.html', {})
		else:
			return render(request, 'db_authentication/password_reset_token_expired.html', {})
	else:
		if token and token.is_valid():
			reset_password_by_token(token, request.POST.get('password'))
			return render(request, 'db_authentication/password_reset_token_success.html', {})
		else:
			return render(request, 'db_authentication/password_reset_token_expired.html', {})

def reset_password_by_token(token: ForgotPasswordToken, password):
	user = User.objects.get(email=token.email)
	user_auth, created = UserAuth.objects.get_or_create(username=user.username)
	user_auth.set_password(password)
	user_auth.save()
	token.expired = True
	token.save()

