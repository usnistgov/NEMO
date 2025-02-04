import contextlib
import re
from logging import getLogger
from typing import Optional

from django.conf import settings
from django.contrib.auth.middleware import RemoteUserMiddleware
from django.http import Http404, HttpResponseForbidden
from django.urls import NoReverseMatch, resolve, reverse
from django.utils.deprecation import MiddlewareMixin

from NEMO.exceptions import InactiveUserError
from NEMO.models import User
from NEMO.utilities import is_ajax

middleware_logger = getLogger(__name__)


class RemoteUserAuthenticationMiddleware(RemoteUserMiddleware):
    def __init__(self, get_response=None):
        self.api_url = None
        try:
            self.api_url = reverse("api-root")
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
                # We cannot use redirect here otherwise we create an infinite loop (calling the middleware again)
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
            return HttpResponseForbidden() if is_ajax(request) else None

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
        if request.user.has_perm("NEMO.can_impersonate_users") and "impersonate_id" in request.session:
            request.user = User.objects.get(pk=request.session["impersonate_id"])


class NEMOAuditlogMiddleware:
    """
    Middleware to couple the request's user to log items. This is accomplished by currying the
    signal receiver with the user from the request (or None if the user is not authenticated).
    """

    def __init__(self, get_response=None):
        self.get_response = get_response

    def __call__(self, request):
        if request.META.get("HTTP_X_FORWARDED_FOR"):
            # In case of proxy, set 'original' address
            remote_addr = request.META.get("HTTP_X_FORWARDED_FOR").split(",")[0]
        else:
            remote_addr = request.META.get("REMOTE_ADDR")

        # Default null context
        context = contextlib.nullcontext()
        if hasattr(request, "user") and request.user.is_authenticated:
            from auditlog.context import set_actor

            actor = request.user
            # Special treatment if the request is coming from the Kiosk or Area access
            try:
                func_path: str = resolve(request.path)._func_path
                if func_path.startswith("NEMO.apps.kiosk") or func_path.startswith("NEMO.apps.area_access"):
                    actor = self.get_actor_for_kiosk_area_access(request)
            except Http404:
                pass
            except Exception as e:
                middleware_logger.warning("Error setting up actor for audit log", exc_info=e)
            context = set_actor(actor=actor, remote_addr=remote_addr)

        with context:
            return self.get_response(request)

    # For Kiosk and Area access plugins, the user is not the one set on the request
    def get_actor_for_kiosk_area_access(self, request) -> Optional[User]:
        badge_number = request.POST.get("badge_number")
        if badge_number:
            return User.objects.get(badge_number=badge_number)
        else:
            customer_id = request.POST.get("customer_id")
            if customer_id:
                return User.objects.get(pk=customer_id)
        return request.user
