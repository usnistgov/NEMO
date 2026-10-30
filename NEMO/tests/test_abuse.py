from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from NEMO.models import User
from NEMO.tests.test_utilities import NEMOTestCaseMixin, create_user_and_project


class AbuseTestCase(NEMOTestCaseMixin, TestCase):
    def test_abuse_permissions(self):
        abuse_url = reverse("abuse")
        user, _ = create_user_and_project()

        # Regular user without permission cannot access
        self.login_as(user)
        response = self.client.get(abuse_url, follow=True)
        self.assert_response_is_landing_page(response)

        # Staff user without permission cannot access
        staff = self.login_as_staff()
        response = self.client.get(abuse_url, follow=True)
        self.assert_response_is_landing_page(response)

        # Facility manager can access
        staff.is_facility_manager = True
        staff.save()
        self.login_as(staff)
        response = self.client.get(abuse_url, follow=True)
        self.assertEqual(response.status_code, 200)

        # Superuser can access
        staff.is_facility_manager = False
        staff.is_superuser = True
        staff.save()
        self.login_as(staff)
        response = self.client.get(abuse_url, follow=True)
        self.assertEqual(response.status_code, 200)

        # User with use_abuse permission can access
        perm = Permission.objects.get(codename="use_abuse")
        user.user_permissions.add(perm)
        user = User.objects.get(pk=user.pk)
        self.login_as(user)
        response = self.client.get(abuse_url, follow=True)
        self.assertEqual(response.status_code, 200)

        # Staff user with use_abuse permission can access
        staff.is_superuser = False
        staff.is_facility_manager = False
        staff.user_permissions.add(perm)
        staff = User.objects.get(pk=staff.pk)
        self.login_as(staff)
        response = self.client.get(abuse_url, follow=True)
        self.assertEqual(response.status_code, 200)

    def test_abuse_navbar_link(self):
        user, _ = create_user_and_project()

        # Regular user without permission does not see Abuse link
        self.login_as(user)
        response = self.client.get(reverse("landing"))
        self.assertNotContains(response, reverse("abuse"))

        # Staff user without permission does not see Abuse link
        staff = self.login_as_staff()
        response = self.client.get(reverse("landing"))
        self.assertNotContains(response, reverse("abuse"))

        # Facility manager sees Abuse link
        staff.is_facility_manager = True
        staff.save()
        self.login_as(staff)
        response = self.client.get(reverse("landing"))
        self.assertContains(response, reverse("abuse"))

        # User with use_abuse permission sees Abuse link
        perm = Permission.objects.get(codename="use_abuse")
        user.user_permissions.add(perm)
        user = User.objects.get(pk=user.pk)
        self.login_as(user)
        response = self.client.get(reverse("landing"))
        self.assertContains(response, reverse("abuse"))
