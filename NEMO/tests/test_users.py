from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from NEMO.tests.test_utilities import NEMOTestCaseMixin, create_user_and_project
from NEMO.views.customization import UserCustomization


class UserTestCase(NEMOTestCaseMixin, TestCase):

    def test_view_user_profile(self):
        customer, customer_project = create_user_and_project()
        self.login_as(customer)
        # Cannot see one's profile if the feature is disabled
        UserCustomization.set("user_allow_profile_view", "")
        response = self.client.get(reverse("view_user", args=[customer.id]))
        self.assertEqual(response.status_code, 400)
        # Now it should work
        UserCustomization.set("user_allow_profile_view", "enabled")
        response = self.client.get(reverse("view_user", args=[customer.id]))
        self.assertEqual(response.status_code, 200)
        # Cannot see someone else's profile even as staff
        self.login_as_staff()
        response = self.client.get(reverse("view_user", args=[customer.id]))
        self.assertEqual(response.status_code, 400)

    def test_impersonate_user(self):
        admin = create_user_and_project(is_staff=True)[0]
        admin.is_superuser = True
        admin.save()
        manager = create_user_and_project(is_staff=True)[0]
        manager.is_facility_manager = True
        manager.user_permissions.add(Permission.objects.get(codename="can_impersonate_users"))
        manager.save()
        staff = create_user_and_project(is_staff=True)[0]
        staff.user_permissions.add(Permission.objects.get(codename="can_impersonate_users"))
        staff.save()
        user = create_user_and_project()[0]
        user_2 = create_user_and_project()[0]
        # 1 admin can impersonate anyone
        self.login_as(admin)
        response = self.client.post(reverse("impersonate"), data={"user_id": manager.id})
        self.assertEqual(response.status_code, 302)
        # 2 facility manager can impersonate anyone except admins
        self.login_as(manager)
        response = self.client.post(reverse("impersonate"), data={"user_id": manager.id})
        self.assertEqual(response.status_code, 302)
        response = self.client.post(reverse("impersonate"), data={"user_id": admin.id})
        self.assertEqual(response.status_code, 403)
        # 3 staff can impersonate only regular users
        self.login_as(staff)
        response = self.client.post(reverse("impersonate"), data={"user_id": admin.id})
        self.assertEqual(response.status_code, 403)
        response = self.client.post(reverse("impersonate"), data={"user_id": manager.id})
        self.assertEqual(response.status_code, 403)
        response = self.client.post(reverse("impersonate"), data={"user_id": staff.id})
        self.assertEqual(response.status_code, 403)
        response = self.client.post(reverse("impersonate"), data={"user_id": user.id})
        self.assertEqual(response.status_code, 302)
        # 4 user cannot impersonate anyone unless he has permission
        self.login_as(user)
        response = self.client.post(reverse("impersonate"), data={"user_id": user_2.id})
        self.assertEqual(response.status_code, 403)
        user.user_permissions.add(Permission.objects.get(codename="can_impersonate_users"))
        user.save()
        response = self.client.post(reverse("impersonate"), data={"user_id": user_2.id})
        self.assertEqual(response.status_code, 302)
