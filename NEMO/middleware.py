import re

from django.http import HttpResponseForbidden
from django.contrib.auth.middleware import RemoteUserMiddleware
from django.conf import settings


class HTTPHeaderAuthenticationMiddleware(RemoteUserMiddleware):
	header = "HTTP_" + getattr(settings, "AUTHENTICATION_HEADER", "AUTHORIZATION")


class SessionTimeout:
	def __init__(self, get_response):
		self.get_response = get_response

	def __call__(self, request):
		return self.get_response(request)

	def process_view(self, request, view_function, view_ordered_arguments, view_named_arguments):
		"""
		This custom middleware exists to provide a smooth experience for public facing NEMO users.
		It processes all requests and redirects a user to the login page when their session times out.
		"""

		# If the user does not yet have a session then take no action.
		if not request.session:
			return None

		# If the user's session has timed out and this is an AJAX request then reply
		# with 403 forbidden because we don't want the AJAX request to produce the login page.
		# The base.html template has a global AJAX error callback to redirect to the logout
		# page when HTTP 403 is received.
		#
		# If the request is normal (instead of AJAX) and the user's session has expired
		# then the @login_required decorator will redirect them to the login page.
		if not request.user.is_authenticated:
			return HttpResponseForbidden() if request.is_ajax() else None

		# If the view is regularly polled by the webpage to update information then expiry refresh should be disabled.
		refresh_disabled = getattr(view_function, 'disable_session_expiry_refresh', False)
		if not refresh_disabled:
			request.session.modified = True


class DeviceDetectionMiddleware:
	def __init__(self, get_response):
		self.get_response = get_response
		self.mobile = re.compile('Mobile|Tablet|Android')

	def __call__(self, request):
		request.device = 'desktop'

		if 'HTTP_USER_AGENT' in request.META:
			user_agent = request.META['HTTP_USER_AGENT']
			if self.mobile.search(user_agent):
				request.device = 'mobile'

		return self.get_response(request)
