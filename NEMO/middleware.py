import re
from logging import getLogger

from django.http import HttpResponseForbidden
from django.contrib.auth.middleware import RemoteUserMiddleware
from django.conf import settings
from django.urls import reverse, NoReverseMatch
from django.utils.deprecation import MiddlewareMixin

from NEMO.exceptions import InactiveUserError
from NEMO.models import User

middleware_logger = getLogger(__name__)


class RemoteUserAuthenticationMiddleware(RemoteUserMiddleware):

	def __init__(self, get_response=None):
		self.api_url = None
		try:
			self.api_url = reverse('api-root')
		except NoReverseMatch:
			pass
		super().__init__(get_response)

	def process_request(self, request):
		# REST API has its own authentication
		if request.path and self.api_url and request.path.startswith(self.api_url):
			return

		try:
			try:
				header_value = request.META[self.header]
			except KeyError:
				# If header is not present, log a warning and continue with processing of base class. (no authentication is happening)
				middleware_logger.debug(f"Header: {self.header} not present or invalid")
			super().process_request(request)
		except (User.DoesNotExist, InactiveUserError):
			from NEMO.views.authentication import all_auth_backends_are_pre_auth
			# Only raise error if all we have are pre_authentication backends and they failed
			if all_auth_backends_are_pre_auth():
				from NEMO.views.authentication import authorization_failed
				return authorization_failed(request)


class HTTPHeaderAuthenticationMiddleware(RemoteUserAuthenticationMiddleware):
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
		refresh_disabled = getattr(view_function, "disable_session_expiry_refresh", False)
		if not refresh_disabled:
			request.session.modified = True


class DeviceDetectionMiddleware:
	def __init__(self, get_response):
		self.get_response = get_response
		self.mobile = re.compile("Mobile|Tablet|Android")

	def __call__(self, request):
		request.device = "desktop"

		if "HTTP_USER_AGENT" in request.META:
			user_agent = request.META["HTTP_USER_AGENT"]
			if self.mobile.search(user_agent):
				request.device = "mobile"

		return self.get_response(request)


class ImpersonateMiddleware(MiddlewareMixin):
	def process_request(self, request):
		if request.user.is_superuser and 'impersonate_id' in request.session:
			request.user = User.objects.get(pk=request.session['impersonate_id'])
