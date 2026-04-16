from django.test import TestCase
from django.urls import reverse

from NEMO.models import Area, PhysicalAccessLevel, User
from NEMO.tests.test_utilities import NEMOTestCaseMixin, create_user_and_project
from NEMO.views.customization import AdjustmentRequestsCustomization


class UserRequestsTestCase(NEMOTestCaseMixin, TestCase):
    def setUp(self):
        self.user, self.project = create_user_and_project()

    def test_user_requests_access_enabled(self):
        self.login_as(self.user)
        # Enable access requests
        area = Area.objects.create(name="Test Area")
        PhysicalAccessLevel.objects.create(
            name="Test Access", area=area, schedule=PhysicalAccessLevel.Schedule.ALWAYS, allow_user_request=True
        )
        User.objects.create(username="manager", is_active=True, is_facility_manager=True)

        response = self.client.get(reverse("user_requests"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["tab"], "access")

    def test_user_requests_buddy_enabled(self):
        self.login_as(self.user)
        # Disable access requests (by not creating manager/access level)
        # Enable buddy requests
        Area.objects.create(name="Test Area", buddy_system_allowed=True)

        response = self.client.get(reverse("user_requests"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["tab"], "buddy")

    def test_user_requests_adjustment_enabled(self):
        self.login_as(self.user)
        # Disable others, enable adjustment
        from NEMO.models import Customization
        from NEMO.views.customization import CustomizationBase

        Customization.objects.update_or_create(name="adjustment_requests_enabled", defaults={"value": "enabled"})
        CustomizationBase.invalidate_cache()

        response = self.client.get(reverse("user_requests"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["tab"], "adjustment")

    def test_user_requests_staff_assistance_default(self):
        self.login_as(self.user)
        # Disable all others
        response = self.client.get(reverse("user_requests"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["tab"], "staff_assistance")

    def test_user_requests_tab_param(self):
        self.login_as(self.user)
        response = self.client.get(reverse("user_requests", kwargs={"tab": "buddy"}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["tab"], "buddy")

        response = self.client.get(reverse("user_requests", kwargs={"tab": "staff_assistance"}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["tab"], "staff_assistance")
