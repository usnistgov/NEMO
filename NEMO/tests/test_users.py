from django.test import TestCase
from django.urls import reverse

from NEMO.tests.test_utilities import create_user_and_project, login_as, login_as_staff
from NEMO.views.customization import UserCustomization


class UserTestCase(TestCase):

    def test_view_user_profile(self):
        customer, customer_project = create_user_and_project()
        login_as(self.client, customer)
        # Cannot see one's profile if the feature is disabled
        UserCustomization.set("user_allow_profile_view", "")
        response = self.client.get(reverse("view_user", args=[customer.id]))
        self.assertEqual(response.status_code, 400)
        # Now it should work
        UserCustomization.set("user_allow_profile_view", "enabled")
        response = self.client.get(reverse("view_user", args=[customer.id]))
        self.assertEqual(response.status_code, 200)
        # Cannot see someone else's profile even as staff
        login_as_staff(self.client)
        response = self.client.get(reverse("view_user", args=[customer.id]))
        self.assertEqual(response.status_code, 400)
