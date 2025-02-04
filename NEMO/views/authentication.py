from _ssl import CERT_REQUIRED, PROTOCOL_TLSv1_2
from base64 import b64decode
from logging import getLogger
from urllib.parse import urljoin, urlparse

from django.conf import settings
from django.contrib.auth import REDIRECT_FIELD_NAME, authenticate, get_backends, login
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.middleware import RemoteUserMiddleware
from django.http import HttpResponse, HttpResponseForbidden, HttpResponseRedirect
from django.shortcuts import redirect, render
from django.urls import resolve, reverse
from django.utils.decorators import method_decorator
from django.utils.module_loading import import_string
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_http_methods
from ldap3 import ANONYMOUS, AUTO_BIND_NO_TLS, Connection, SIMPLE, Server, Tls
from ldap3.core.exceptions import LDAPBindError, LDAPException

from NEMO.exceptions import InactiveUserError
from NEMO.middleware import (
    HTTPHeaderAuthenticationMiddleware,
    ImpersonateMiddleware,
    RemoteUserAuthenticationMiddleware,
)
from NEMO.models import User
from NEMO.views.customization import get_media_file_contents

auth_logger = getLogger(__name__)


def get_full_class_name(clas):
    return clas.__module__ + "." + clas.__name__


def get_auth_backends():
    return [type(backend) for backend in get_backends()]


def get_pre_authentication_backends():
    """Returns a list of pre_authentication backends. Those require the user to be authenticated before getting to NEMO"""
    pre_auth_backends = getattr(
        settings,
        "PRE_AUTH_BACKENDS",
        [
            get_full_class_name(RemoteUserAuthenticationBackend),
            get_full_class_name(NginxKerberosAuthorizationHeaderAuthenticationBackend),
        ],
    )
    return [import_string(pre_auth_backend) for pre_auth_backend in pre_auth_backends]


def all_auth_backends_are_pre_auth():
    return all([auth_backend in get_pre_authentication_backends() for auth_backend in get_auth_backends()])


def check_user_exists_and_active(backend: ModelBackend, username: str) -> User:
    # The user must exist in the database
    try:
        user = User.objects.get(username__iexact=username)
    except User.DoesNotExist:
        auth_logger.warning(
            f"User {username} attempted to authenticate with {type(backend).__name__}, but that username does not exist in the database. The user was denied access."
        )
        raise
    # The user must be marked active.
    if not user.is_active:
        auth_logger.warning(
            f"User {username} attempted to authenticate with {type(backend).__name__}, but that user is marked inactive in the database. The user was denied access."
        )
        raise InactiveUserError(user=username)
    auth_logger.debug(f"User {username} exists in the database and is active.")
    return user


def check_pre_authentication_backends(request):
    if any([pre_auth_backend in get_auth_backends() for pre_auth_backend in get_pre_authentication_backends()]):
        # check for improper configuration
        if (
            get_full_class_name(RemoteUserMiddleware) not in settings.MIDDLEWARE
            and get_full_class_name(HTTPHeaderAuthenticationMiddleware) not in settings.MIDDLEWARE
            and get_full_class_name(RemoteUserAuthenticationMiddleware) not in settings.MIDDLEWARE
        ):
            error_message = "To use this backend you need to add either RemoteUserMiddleware, RemoteUserAuthenticationMiddleware or HTTPHeaderAuthenticationMiddleware to settings.MIDDLEWARE"
            auth_logger.error(error_message)
            return HttpResponse(error_message, status=400)
        # if the user is already in the request and authenticated, send to landing page
        elif hasattr(request, "user") and request.user.is_authenticated:
            return HttpResponseRedirect(reverse("landing"))
        elif all_auth_backends_are_pre_auth():
            # We only have pre_auth backends, and the user isn't authenticated at this point, fail.
            return HttpResponse("There was an error pre-authenticating the user", status=400)


def base_64_decode_basic_auth(remote_user: str):
    """This method returns username, password from basic authentication base64 encoded remote user"""
    pieces = remote_user.split()
    if len(pieces) != 2:
        return None
    if pieces[0] != "Basic":
        return None
    return b64decode(pieces[1]).decode().split(":")


class RemoteUserAuthenticationBackend(ModelBackend):
    """The web server performs authentication and passes the username remotely. (header or env)"""

    create_unknown_user = False

    # This override not matching is intended
    def authenticate(self, request, remote_user):
        if not remote_user:
            return
        username = self.clean_username(remote_user)
        user = check_user_exists_and_active(self, username)
        # All security checks passed so let the user in.
        auth_logger.debug(
            f"User {username} successfully authenticated with {type(self).__name__} and was granted access."
        )
        return user

    def clean_username(self, username):
        """
        Usernames arrive in the form user@DOMAIN.NAME.
        This function chops off Kerberos realm information (i.e. the '@' and everything after).
        """
        return username.partition("@")[0]


class NginxKerberosAuthorizationHeaderAuthenticationBackend(RemoteUserAuthenticationBackend):
    """The web server performs Kerberos authentication and passes the username in via the HTTP_AUTHORIZATION header."""

    def clean_username(self, username):
        """
        Usernames arrive encoded in base 64, similar to Basic authentication, but with a bogus password set (since .
        This function chops off Kerberos realm information (i.e. the '@' and everything after).
        """
        if not username:
            return None
        credentials = base_64_decode_basic_auth(username)
        return credentials if credentials is None else super().clean_username(credentials[0])


class LDAPAuthenticationBackend(ModelBackend):
    """This class provides LDAP authentication against an LDAP or Active Directory server."""

    @method_decorator(sensitive_post_parameters("password"))
    def authenticate(self, request, username=None, password=None, **keyword_arguments):
        # Check for remote user in extra arguments if no username and password.
        # In case of basic authentication
        if not username or not password:
            if "remote_user" in keyword_arguments:
                credentials = base_64_decode_basic_auth(keyword_arguments["remote_user"])
                if credentials:
                    username, password = credentials[0], credentials[1]
                else:
                    return None
            else:
                return None

        user = check_user_exists_and_active(self, username)

        is_authenticated_with_ldap = False
        errors = []
        for server in settings.LDAP_SERVERS:
            try:
                port = server.get("port", 636)
                use_ssl = server.get("use_ssl", True)
                bind_as_authentication = server.get("bind_as_authentication", True)
                domain = server.get("domain")
                username_format = domain + "\\{}" if domain else server.get("username_format", "{}")
                t = Tls(validate=CERT_REQUIRED, version=PROTOCOL_TLSv1_2, ca_certs_file=server.get("certificate"))
                s = Server(server["url"], port=port, use_ssl=use_ssl, tls=t)
                # We are securing the connection to the server with use_ssl, so no need for TLS
                auto_bind = AUTO_BIND_NO_TLS
                ldap_bind_user = username_format.format(username)
                if not bind_as_authentication:
                    # binding to LDAP first, then search for user
                    bind_username = server.get("bind_username", None)
                    bind_username = username_format.format(bind_username) if bind_username is not None else None
                    bind_password = server.get("bind_password", None)
                    authentication = SIMPLE if bind_username and bind_password else ANONYMOUS
                    c = Connection(
                        s,
                        user=bind_username,
                        password=bind_password,
                        auto_bind=auto_bind,
                        authentication=authentication,
                        raise_exceptions=True,
                    )
                    search_username_field = server.get("search_username_field", "uid")
                    search_attribute = server.get("search_attribute", "cn")
                    search = c.search(
                        server["base_dn"], f"({search_username_field}={username})", attributes=[search_attribute]
                    )
                    if not search or search_attribute not in c.response[0].get("attributes", []):
                        # no results, unbind and continue to next server
                        c.unbind()
                        errors.append(
                            f"User {username} attempted to authenticate with LDAP ({server['url']}), but the search with dn:{server['base_dn']}, username_field:{search_username_field} and attribute:{search_attribute} did not return any results. The user was denied access"
                        )
                        continue
                    else:
                        # we got results, get the dn that will be used for binding authentication
                        response = c.response[0]
                        ldap_bind_user = response["dn"]
                        c.unbind()

                # let's proceed with binding using the user trying to authenticate
                c = Connection(
                    s,
                    user=ldap_bind_user,
                    password=password,
                    auto_bind=auto_bind,
                    authentication=SIMPLE,
                    raise_exceptions=True,
                )
                c.unbind()
                # At this point the user successfully authenticated to at least one LDAP server.
                is_authenticated_with_ldap = True
                auth_logger.debug(f"User {username} was successfully authenticated with LDAP ({server['url']})")
                break
            except LDAPBindError as e:
                errors.append(
                    f"User {username} attempted to authenticate with LDAP ({server['url']}), but entered an incorrect password. The user was denied access: {str(e)}"
                )
            except LDAPException as e:
                errors.append(
                    f"User {username} attempted to authenticate with LDAP ({server['url']}), but an error occurred. The user was denied access: {str(e)}"
                )

        if is_authenticated_with_ldap:
            return user
        else:
            for error in errors:
                auth_logger.warning(error)
            return None


@require_http_methods(["GET", "POST"])
@sensitive_post_parameters("password")
def login_user(request):
    # check to make sure we don't have a misconfiguration. pre-authentication backends need to use middleware
    response = check_pre_authentication_backends(request)
    if response:
        return response

    dictionary = {
        "login_banner": get_media_file_contents("login_banner.html"),
        "user_name_or_password_incorrect": False,
    }

    # if we are dealing with anything else than POST, send to login page
    if request.method != "POST":
        return render(request, "login.html", dictionary)
    # Otherwise try to log the user in
    else:
        username = request.POST.get("username", "")
        password = request.POST.get("password", "")
        try:
            user = authenticate(request, username=username, password=password)
        except (User.DoesNotExist, InactiveUserError):
            return redirect("authorization_failed")

        if user:
            login(request, user)
            try:
                next_page = request.GET[REDIRECT_FIELD_NAME]
                resolve(
                    urljoin(next_page, urlparse(next_page).path)
                )  # Make sure the next page is a legitimate URL for NEMO
            except:
                next_page = reverse("landing")
            return HttpResponseRedirect(next_page)
        dictionary["user_name_or_password_incorrect"] = True
        return render(request, "login.html", dictionary)


@require_GET
def authorization_failed(request):
    authorization_page = get_media_file_contents("authorization_failed.html")
    return render(request, "authorization_failed.html", {"authorization_failed": authorization_page})


@require_http_methods(["GET", "POST"])
def impersonate(request):
    impersonate_middleware_name = get_full_class_name(ImpersonateMiddleware)
    if impersonate_middleware_name not in settings.MIDDLEWARE:
        return HttpResponse(
            f"'{impersonate_middleware_name}' needs to be in settings.MIDDLEWARE for this feature to work", status=400
        )
    if "unimpersonate" in request.GET and "impersonate_id" in request.session:
        del request.session["impersonate_id"]
        del request.session["impersonated_user"]
        return redirect(reverse("landing"))
    if not request.user.has_perm("NEMO.can_impersonate_users"):
        return HttpResponseForbidden()
    user: User = request.user
    if request.method == "POST":
        user_id = request.POST["user_id"]
        impersonated_user: User = User.objects.get(pk=user_id)
        # check roles to make sure regular users cannot impersonate admins or facility managers
        if user.is_superuser:
            pass
        elif user.is_facility_manager:
            # Facility managers can impersonate anyone except admins
            if impersonated_user.is_superuser:
                return HttpResponseForbidden("You cannot impersonate an administrator")
        else:
            # Anyone else (staff non admin, non facility manager and regular users) can only impersonate regular users
            if impersonated_user.is_any_part_of_staff:
                return HttpResponseForbidden("You cannot only impersonate regular users")
        request.session["impersonate_id"] = int(user_id)
        request.session["impersonated_user"] = str(impersonated_user)
        return redirect(reverse("landing"))
    else:
        users = User.objects.filter(is_active=True)
        if user.is_superuser:
            pass
        elif user.is_facility_manager:
            users = users.exclude(is_superuser=True)
        else:
            users = (
                users.exclude(is_facility_manager=True)
                .exclude(is_superuser=True)
                .exclude(is_accounting_officer=True)
                .exclude(is_staff=True)
                .exclude(is_user_office=True)
            )
        return render(request, "impersonate.html", {"users": users})
