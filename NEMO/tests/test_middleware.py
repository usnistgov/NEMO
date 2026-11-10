from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from NEMO.middleware import HTTPHeaderAuthenticationMiddleware, RemoteUserAuthenticationMiddleware
from NEMO.tests.test_utilities import NEMOTestCaseMixin, create_user_and_project


class RemoteUserAuthenticationMiddlewareTestCase(NEMOTestCaseMixin, TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_health_check_bypasses_remote_user_authentication(self):
        middleware = RemoteUserAuthenticationMiddleware(get_response=lambda r: None)
        request = self.factory.get(reverse("health_check"))
        request.user = AnonymousUser()

        with patch("NEMO.middleware.middleware_logger.debug") as mock_debug:
            middleware.process_request(request)
            mock_debug.assert_not_called()

    def test_health_check_bypasses_http_header_authentication(self):
        middleware = HTTPHeaderAuthenticationMiddleware(get_response=lambda r: None)
        request = self.factory.get(reverse("health_check"))
        request.user = AnonymousUser()

        with patch("NEMO.middleware.middleware_logger.debug") as mock_debug:
            middleware.process_request(request)
            mock_debug.assert_not_called()

    @override_settings(AUTHENTICATION_HEADER="X_REMOTE_USER")
    def test_health_check_with_custom_header_setting(self):
        middleware = HTTPHeaderAuthenticationMiddleware(get_response=lambda r: None)
        request = self.factory.get(reverse("health_check"))
        request.user = AnonymousUser()

        with patch("NEMO.middleware.middleware_logger.debug") as mock_debug:
            middleware.process_request(request)
            mock_debug.assert_not_called()

    def test_regular_view_logs_missing_header(self):
        middleware = RemoteUserAuthenticationMiddleware(get_response=lambda r: None)
        request = self.factory.get(reverse("landing"))
        request.user = AnonymousUser()

        with patch("NEMO.middleware.middleware_logger.debug") as mock_debug:
            middleware.process_request(request)
            mock_debug.assert_called_once_with(f"Header: {middleware.header} not present or invalid")

    def test_api_view_bypasses_remote_user_authentication(self):
        middleware = RemoteUserAuthenticationMiddleware(get_response=lambda r: None)
        request = self.factory.get(reverse("api-root"))
        request.user = AnonymousUser()

        with patch("NEMO.middleware.middleware_logger.debug") as mock_debug:
            middleware.process_request(request)
            mock_debug.assert_not_called()

    def test_client_get_health_check(self):
        response = self.client.get(reverse("health_check"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"OK")

    def test_health_check_subpath_or_prefix_not_bypassed(self):
        middleware = RemoteUserAuthenticationMiddleware(get_response=lambda r: None)
        request = self.factory.get(reverse("health_check") + "_extra/")
        request.user = AnonymousUser()

        with patch("NEMO.middleware.middleware_logger.debug") as mock_debug:
            middleware.process_request(request)
            mock_debug.assert_called_once_with(f"Header: {middleware.header} not present or invalid")

    @override_settings(
        AUTHENTICATION_BACKENDS=[
            "NEMO.views.authentication.GenericRemoteUserAuthenticationBackend",
        ]
    )
    def test_remote_user_authentication_user_does_not_exist_returns_authorization_failed(self):
        dummy_view = lambda r: HttpResponse("reached view")
        middleware = RemoteUserAuthenticationMiddleware(get_response=dummy_view)
        request = self.factory.get(reverse("landing"), REMOTE_USER="nonexistent_user")
        request.user = AnonymousUser()
        SessionMiddleware(lambda r: None).process_request(request)

        response = middleware(request)
        self.assertIsNotNone(response)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Authorization failed", response.content)

    @override_settings(
        AUTHENTICATION_HEADER="REMOTE_USER",
        AUTHENTICATION_BACKENDS=[
            "NEMO.views.authentication.GenericRemoteUserAuthenticationBackend",
        ],
    )
    def test_http_header_authentication_user_does_not_exist_returns_authorization_failed(self):
        dummy_view = lambda r: HttpResponse("reached view")
        middleware = HTTPHeaderAuthenticationMiddleware(get_response=dummy_view)
        request = self.factory.get(reverse("landing"), HTTP_REMOTE_USER="nonexistent_user")
        request.user = AnonymousUser()
        SessionMiddleware(lambda r: None).process_request(request)

        response = middleware(request)
        self.assertIsNotNone(response)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Authorization failed", response.content)

    @override_settings(
        AUTHENTICATION_HEADER="REMOTE_USER",
        AUTHENTICATION_BACKENDS=[
            "NEMO.views.authentication.GenericRemoteUserAuthenticationBackend",
        ],
    )
    def test_http_header_authentication_user_exists_calls_view(self):
        user, _ = create_user_and_project()
        dummy_view = lambda r: HttpResponse("reached view")
        middleware = HTTPHeaderAuthenticationMiddleware(get_response=dummy_view)
        request = self.factory.get(reverse("landing"), HTTP_REMOTE_USER=user.username)
        request.user = AnonymousUser()
        SessionMiddleware(lambda r: None).process_request(request)

        response = middleware(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"reached view")
        self.assertEqual(request.user, user)
        self.assertTrue(request.user.is_authenticated)
