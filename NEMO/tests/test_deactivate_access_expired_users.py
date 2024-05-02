from datetime import date, timedelta

from django.test import TestCase

from NEMO.models import Account, Project, User, UserType
from NEMO.views.customization import UserCustomization
from NEMO.views.timed_services import do_deactivate_access_expired_users


class UserActiveAccessExpirationTestCase(TestCase):
    def setUp(self):
        self.expired_user: User = User.objects.create(
            username="mctest", first_name="Testy", last_name="McTester", email="testy.mctester@example.com"
        )
        self.user: User = User.objects.create(
            username="user", first_name="User", last_name="McTester", email="user.mctester@example.com"
        )
        self.project: Project = Project.objects.create(
            name="Project 1", application_identifier="P1", account=Account.objects.create(name="Account 1")
        )
        self.user.projects.add(self.project)

    def test_qualification_expiration_nothing(self):
        do_deactivate_access_expired_users()
        for user in User.objects.all():
            self.assertTrue(user.is_active)

    def test_qualification_expiration_enabled_no_types(self):
        # expired user's access expired yesterday
        self.expired_user.access_expiration = date.today() - timedelta(days=1)
        self.expired_user.save()

        # not enabled, nothing happens
        do_deactivate_access_expired_users()
        for user in User.objects.all():
            self.assertTrue(user.is_active)

        # now enable it for users with no types
        UserCustomization.set("user_access_expiration_no_type", "enabled")
        do_deactivate_access_expired_users()
        for user in User.objects.all():
            if user.id == self.expired_user.id:
                self.assertFalse(user.is_active)
            else:
                self.assertTrue(user.is_active)

    def test_qualification_expiration_enabled_types(self):
        user_type = UserType.objects.create(name="Student", display_order=1)
        # expired user's access expired yesterday
        self.expired_user.access_expiration = date.today() - timedelta(days=1)
        self.expired_user.save()

        # now enable it for users with type, nothing should happen
        UserCustomization.set("user_access_expiration_types", str(user_type.id))
        do_deactivate_access_expired_users()
        for user in User.objects.all():
            self.assertTrue(user.is_active)

        # set the type, it should now work
        self.expired_user.type = user_type
        self.expired_user.save()
        do_deactivate_access_expired_users()
        for user in User.objects.all():
            if user.id == self.expired_user.id:
                self.assertFalse(user.is_active)
            else:
                self.assertTrue(user.is_active)

    def test_qualification_expiration_enabled_types_no_type(self):
        user_type = UserType.objects.create(name="Student", display_order=1)
        # expired user's access expired yesterday
        self.expired_user.access_expiration = date.today() - timedelta(days=1)
        self.expired_user.type = user_type
        self.expired_user.save()

        # now enable it for users with no type, nothing should happen
        UserCustomization.set("user_access_expiration_no_type", "enabled")
        do_deactivate_access_expired_users()
        for user in User.objects.all():
            self.assertTrue(user.is_active)

        # try both, set expiration on a second user, and enabled both. both users should be deactivated
        UserCustomization.set("user_access_expiration_types", str(user_type.id))
        self.user.access_expiration = date.today() - timedelta(days=2)
        self.user.save()
        do_deactivate_access_expired_users()
        for user in User.objects.all():
            self.assertFalse(user.is_active)

    def test_qualification_expiration_enabled_buffer_days(self):
        # expired user's access expired yesterday
        self.expired_user.access_expiration = date.today() - timedelta(days=1)
        self.expired_user.save()

        # now enable it for users with no types, but set a buffer for 10 days
        UserCustomization.set("user_access_expiration_no_type", "enabled")
        UserCustomization.set("user_access_expiration_buffer_days", "10")
        # nothing happens
        for user in User.objects.all():
            self.assertTrue(user.is_active)

        # set expiration to 10 days in the past, should work
        self.expired_user.access_expiration = date.today() - timedelta(days=1)
        do_deactivate_access_expired_users()
        for user in User.objects.all():
            if user.id == self.expired_user.id:
                self.assertFalse(user.is_active)
            else:
                self.assertTrue(user.is_active)

    def test_qualification_expiration_enabled_future(self):
        # expired user's access expires today
        self.expired_user.access_expiration = date.today()
        self.expired_user.save()

        # now enable it for users with no types
        UserCustomization.set("user_access_expiration_no_type", "enabled")
        # nothing happens
        for user in User.objects.all():
            self.assertTrue(user.is_active)
