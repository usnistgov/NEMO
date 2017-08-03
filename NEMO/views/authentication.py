from _ssl import PROTOCOL_TLSv1, CERT_REQUIRED
from logging import exception

from django.conf import settings
from django.contrib.auth import authenticate, login, REDIRECT_FIELD_NAME, logout
from django.contrib.auth.backends import RemoteUserBackend
from django.http import HttpResponseRedirect, HttpResponseNotFound
from django.shortcuts import render
from django.urls import reverse, resolve
from django.views.decorators.http import require_http_methods, require_GET
from ldap3 import Tls, Server, Connection, AUTO_BIND_TLS_BEFORE_BIND, SIMPLE
from ldap3.core.exceptions import LDAPBindError, LDAPExceptionError

from NEMO.models import User


class RemoteUserAuthenticationBackend(RemoteUserBackend):
	""" The web server performs Kerberos authentication and passes the user name in via the REMOTE_USER environment variable. """
	create_unknown_user = False

	def authenticate(self, request, remote_user):
		# Run Django's normal authentication checks here. It will attempt to find the user in the database.
		user = super(RemoteUserAuthenticationBackend, self).authenticate(request, remote_user)

		# Perform any custom security checks below.
		# Returning None blocks the user's access.

		# The user must exist in the database & RemoteUserBackend.authenticate must have succeeded.
		if not user:
			return

		# The user must be marked active.
		if not user.is_active:
			return

		# All security checks passed so let the user in.
		return user

	def clean_username(self, username):
		"""
		User names arrive in the form user@DOMAIN.NAME.
		This function chops off Kerberos realm information (i.e. the '@' and everything after).
		"""
		return username.partition('@')[0]


class LDAPAuthenticationBackend(object):
	""" This class provides LDAP authentication against an LDAP or Active Directory server. """
	def authenticate(self, username, password):
		if len(username) == 0 or len(password) == 0:
			return None

		# The user must exist in the database
		try:
			user = User.objects.get(username=username)
		except User.DoesNotExist:
			return None

		# The user must be marked active.
		if not user.is_active:
			return None

		for server in settings.LDAP_SERVERS:
			try:
				t = Tls(validate=CERT_REQUIRED, version=PROTOCOL_TLSv1, ca_certs_file=server['certificate'])
				s = Server(server['url'], port=636, use_ssl=True, tls=t)
				c = Connection(s, user='{}\\{}'.format(server['domain'], username), password=password, auto_bind=AUTO_BIND_TLS_BEFORE_BIND, authentication=SIMPLE)
				c.unbind()
				# At this point the user successfully authenticated to at least one LDAP server.
				return user
			except LDAPBindError as e:
				pass  # When this error is caught it means the username and password were invalid against the LDAP server.
			except LDAPExceptionError as e:
				exception(e)

		# The user did not successfully authenticate to any of the LDAP servers.
		return None

	def get_user(self, user_id):
		# Attempt to find the user in the database.
		try:
			return User.objects.get(id=user_id)
		except User.DoesNotExist:
			return None


@require_http_methods(['GET', 'POST'])
def login_user(request):
	if 'views.authentication.RemoteUserAuthenticationBackend' in settings.AUTHENTICATION_BACKENDS:
		if request.user.is_authenticated:
			return HttpResponseRedirect(reverse('landing'))
		else:
			return render(request, 'authorization_failed.html')

	if request.method == 'GET':
		return render(request, 'login.html')
	username = request.POST.get('username', '')
	password = request.POST.get('password', '')
	user = authenticate(username=username, password=password)
	if user:
		login(request, user)
		try:
			next_page = request.GET[REDIRECT_FIELD_NAME]
			resolve(next_page)  # Make sure the next page is a legitimate URL for NEMO
		except:
			next_page = reverse('landing')
		return HttpResponseRedirect(next_page)
	return render(request, 'login.html', {'user_name_or_password_incorrect': True})


@require_GET
def logout_user(request):
	if 'views.authentication.RemoteUserAuthenticationBackend' in settings.AUTHENTICATION_BACKENDS:
		return HttpResponseNotFound()
	logout(request)
	return HttpResponseRedirect(reverse('login'))
