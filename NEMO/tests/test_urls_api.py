from datetime import datetime

from django.conf import settings
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from NEMO.models import User
from NEMO.tests.test_utilities import NEMOTestCaseMixin
from NEMO.urls import router


class TestAPIUrls(NEMOTestCaseMixin, TestCase):
    def setUp(self):
        user = User.objects.create(username="test", is_superuser=True)
        self.client = APIClient()
        self.login_as(user)

    def test_all_api_urls(self):
        # Iterate through all registered URLs in the DRF router
        for prefix, viewset, basename in router.registry:
            # Get list of routes for this prefix/viewset
            routes = router.get_routes(viewset)
            for route in routes:
                # Reverse the list path
                try:
                    full_url = reverse(f"{basename}-{route.mapping['get']}")
                except Exception:
                    continue  # Skip if URL cannot be reversed

                try:
                    # Make a GET request to the URL (or any method supported)
                    today = datetime.now().date().strftime(settings.DATE_INPUT_FORMATS[0])
                    data = None if basename != "billing" else {"start": today, "end": today}
                    response = self.client.get(full_url, data=data)
                    # Assert that the response is acceptable
                    self.assertEqual(
                        response.status_code,
                        status.HTTP_200_OK,
                        msg=f"URL {full_url} returned unexpected status code {response.status_code}",
                    )
                except Exception as error:
                    self.fail(f"Error while testing URL {full_url}: {error}")
