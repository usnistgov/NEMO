from http import HTTPStatus
from logging import getLogger
from urllib.parse import urljoin

import requests
from django.conf import settings

identity_service_logger = getLogger(__name__)


class IdentityService:
    def __init__(self):
        self.config = getattr(settings, "IDENTITY_SERVICE", {})
        self.available = self.config.get("available", False)
        self.url = self.config.get("url", "")
        self.domains = self.config.get("domains", [])
        self.timeout = self.config.get("timeout", 3)
        self.none = None, None

    def get_externally_managed_areas(self) -> tuple[list | None, str | None]:
        if not self.available:
            return self.none
        try:
            url = urljoin(self.url, "/areas/")
            result = requests.get(url, timeout=self.timeout)
            if result.status_code == HTTPStatus.OK:
                return result.json(), None
            else:
                warning = "The identity service encountered a problem while attempting to return a list of externally managed areas. The administrator has been notified to resolve the problem."
                log_message = f"{warning} The HTTP error was {result.status_code}: {result.text}"
                identity_service_logger.error(log_message)
                return None, warning
        except Exception as e:
            from NEMO.views.customization import ApplicationCustomization

            site_title = ApplicationCustomization.get("site_title")
            warning = f"There was a problem communicating with the identity service. {site_title} is unable to retrieve the list of externally managed areas. The administrator has been notified to resolve the problem."
            log_message = f"{warning} An exception was encountered: {type(e).__name__} - {str(e)}"
            identity_service_logger.error(log_message)
            return None, warning

    def get_user_identity_information(self, username, domain) -> tuple[dict | None, str | None]:
        if not self.available:
            return self.none
        try:
            parameters = {"username": username, "domain": domain}
            result = requests.get(self.url, params=parameters, timeout=self.timeout)
            if result.status_code == HTTPStatus.OK:
                return result.json(), None
            elif result.status_code == HTTPStatus.NOT_FOUND:
                warning = f"The identity service could not find username {username} on the {domain} domain. Does the user's account reside on a different domain? If so, select that domain now and save the user information."
                return {}, warning
            else:
                warning = "The identity service encountered a problem while attempting to search for a user. The administrator has been notified to resolve the problem."
                log_message = f"{warning} The HTTP error was {result.status_code}: {result.text}"
                identity_service_logger.error(log_message)
                return None, warning
        except Exception as e:
            from NEMO.views.customization import ApplicationCustomization

            site_title = ApplicationCustomization.get("site_title")
            warning = f"There was a problem communicating with the identity service. {site_title} is unable to search for a user. The administrator has been notified to resolve the problem."
            log_message = f"{warning} An exception was encountered: {type(e).__name__} - {str(e)}"
            identity_service_logger.error(log_message)
            return None, warning

    def delete_user(self, username, domain) -> tuple[bool | None, str | None]:
        if not self.available:
            return self.none
        try:
            parameters = {"username": username, "domain": domain}
            result = requests.delete(self.url, data=parameters, timeout=self.timeout)
            # If the delete succeeds, or the user is not found, then everything is ok.
            if result.status_code in (HTTPStatus.OK, HTTPStatus.NOT_FOUND):
                return True, None
            else:
                warning = "The user information was not modified because the identity service could not delete the corresponding domain account. The administrator has been notified to resolve the problem."
                log_message = f"The identity service encountered a problem while attempting to delete a user. The HTTP error is {result.status_code}: {result.text}"
                identity_service_logger.error(log_message)
                return None, warning
        except Exception as e:
            warning = "The user information was not modified because the identity service could not delete the corresponding domain account. The administrator has been notified to resolve the problem."
            log_message = f"There was a problem communicating with the identity service while attempting to delete a user. An exception was encountered: {type(e).__name__} - {str(e)}"
            identity_service_logger.error(log_message)
            return None, warning

    def update_user(
        self, username, domain, badge_number=None, email=None, access_expiration=None, requested_areas=None
    ) -> tuple[bool | None, str | None]:
        if not self.available:
            return self.none
        try:
            parameters = {
                "username": username,
                "domain": domain,
            }
            if badge_number is not None:
                parameters["badge_number"] = badge_number
            if email is not None:
                parameters["email"] = email
            if access_expiration is not None:
                parameters["access_expiration"] = access_expiration
            if requested_areas is not None:
                parameters["requested_areas"] = requested_areas
            result = requests.put(self.url, data=parameters, timeout=self.timeout)
            if result.status_code == HTTPStatus.OK:
                return True, None
            elif result.status_code == HTTPStatus.NOT_FOUND:
                warning = "The username was not found on this domain. Did you spell the username correctly in this form and did you select the correct domain? Ensure the user exists on the domain in order to proceed."
                return False, warning
            else:
                warning = "The user information was not modified because the identity service encountered a problem while creating the corresponding domain account. The administrator has been notified to resolve the problem."
                log_message = f"The identity service encountered a problem while attempting to modify a user. The HTTP error is {result.status_code}: {result.text}"
                identity_service_logger.error(log_message)
                return None, warning
        except Exception as e:
            warning = "The user information was not modified because the identity service encountered a problem while creating the corresponding domain account. The administrator has been notified to resolve the problem."
            log_message = f"There was a problem communicating with the identity service while attempting to modify a user. An exception was encountered: {type(e).__name__} - {str(e)}"
            identity_service_logger.error(log_message)
            return None, warning

    def add_user_area(self, username, domain, requested_area) -> tuple[bool | None, str | None]:
        if not self.available:
            return self.none
        try:
            parameters = {
                "username": username,
                "domain": domain,
                "requested_area": requested_area,
            }
            result = requests.put(urljoin(self.url, "/add/"), data=parameters, timeout=self.timeout)
            if result.status_code == HTTPStatus.OK:
                return True, None
            else:
                identity_service_logger.error(
                    f"The identity service encountered a problem while attempting to add an area to a user. The HTTP error is {result.status_code}: {result.text}"
                )
                return self.none
        except Exception as e:
            identity_service_logger.error(
                f"There was a problem communicating with the identity service while attempting to add an area to a user. An exception was encountered: {type(e).__name__} - {str(e)}"
            )
            return self.none

    def reset_password(self, username, domain) -> tuple[bool | None, str | None]:
        if not self.available:
            return self.none
        try:
            parameters = {"username": username, "domain": domain}
            result = requests.post(urljoin(self.url, "/reset_password/"), data=parameters, timeout=self.timeout)
            if result.status_code == HTTPStatus.OK:
                return True, None
            else:
                warning = f"The identity service returned HTTP error code {result.status_code}. {result.text}"
                return None, warning
        except Exception as e:
            warning = f"Exception caught: {type(e).__name__}. {str(e)}"
            return None, warning

    def unlock_account(self, username, domain) -> tuple[bool | None, str | None]:
        if not self.available:
            return self.none
        try:
            parameters = {"username": username, "domain": domain}
            result = requests.post(urljoin(self.url, "/unlock_account/"), data=parameters, timeout=self.timeout)
            if result.status_code == HTTPStatus.OK:
                return True, None
            else:
                warning = f"The identity service returned HTTP error code {result.status_code}. {result.text}"
                return None, warning
        except Exception as e:
            warning = f"Exception caught: {type(e).__name__}. {str(e)}"
            return None, warning


identity_service = IdentityService()
