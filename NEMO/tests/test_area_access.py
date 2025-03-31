import datetime

from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from NEMO.models import (
    Account,
    Area,
    AreaAccessRecord,
    Customization,
    Door,
    Interlock,
    InterlockCard,
    InterlockCardCategory,
    PhysicalAccessLevel,
    Project,
    User,
)
from NEMO.tests.test_utilities import (
    create_user_and_project,
    login_as_staff,
    login_as_user,
    login_as_user_with_permissions,
    test_response_is_failed_login,
    test_response_is_landing_page,
)


class AreaAccessGetTestCase(TestCase):
    def test_area_access_page_by_staff(self):
        login_as_staff(self.client)
        response = self.client.post(reverse("area_access"), {}, follow=True)
        self.assertEqual(response.status_code, 405)  # POST isn't accepted, only GET
        response = self.client.get(reverse("area_access"), {}, follow=True)
        self.assertTrue("area_access" in response.request["PATH_INFO"])
        self.assertEqual(response.status_code, 200)

    def test_area_access_page_by_user(self):
        login_as_user(self.client)
        response = self.client.get(reverse("area_access"), {}, follow=True)
        test_response_is_landing_page(self, response)  # since user is not staff, it should redirect to landing

    def test_area_access_page_by_anonymous(self):
        response = self.client.get(reverse("area_access"), {}, follow=True)
        test_response_is_failed_login(self, response)


class KioskAreaAccess(TestCase):
    door: Door = None

    def setUp(self):
        global door
        interlock_card_category = InterlockCardCategory.objects.get(key="stanford")
        interlock_card = InterlockCard.objects.create(
            server="server.com", port=80, number=1, even_port=1, odd_port=2, category=interlock_card_category
        )
        interlock = Interlock.objects.create(card=interlock_card, channel=1)
        area = Area.objects.create(name="Cleanroom")
        door = Door.objects.create(name="test_door", interlock=interlock)
        door.areas.set([area])

    def test_welcome_screen_fails(self):
        response = self.client.post(reverse("welcome_screen", kwargs={"door_id": door.id}), follow=True)
        test_response_is_failed_login(self, response)
        login_as_user(self.client)
        response = self.client.post(reverse("welcome_screen", kwargs={"door_id": door.id}), follow=True)
        test_response_is_landing_page(self, response)  # landing since we don't have the right credentials
        login_as_user_with_permissions(self.client, ["add_areaaccessrecord"])
        response = self.client.post(reverse("welcome_screen", kwargs={"door_id": door.id}), follow=True)
        self.assertEqual(response.status_code, 405)  # POST isn't accepted, only GET
        response = self.client.get(reverse("welcome_screen", kwargs={"door_id": 999}), follow=True)
        self.assertEqual(response.status_code, 404)  # wrong door id

        response = self.client.get(reverse("welcome_screen", kwargs={"door_id": door.id}), follow=True)
        self.assertEqual(response.status_code, 200)  # All good now
        self.assertTrue("welcome_screen" in response.request["PATH_INFO"])

    def test_farewell_screen_fails(self):
        response = self.client.post(reverse("farewell_screen", kwargs={"door_id": door.id}), follow=True)
        test_response_is_failed_login(self, response)
        login_as_user(self.client)
        response = self.client.post(reverse("farewell_screen", kwargs={"door_id": door.id}), follow=True)
        test_response_is_landing_page(self, response)  # landing since we don't have the right credentials
        login_as_user_with_permissions(self.client, ["change_areaaccessrecord"])
        response = self.client.post(reverse("farewell_screen", kwargs={"door_id": door.id}), follow=True)
        self.assertEqual(response.status_code, 405)  # POST isn't accepted, only GET
        response = self.client.get(reverse("farewell_screen", kwargs={"door_id": 999}), follow=True)
        self.assertEqual(response.status_code, 404)  # wrong door id

        response = self.client.get(reverse("farewell_screen", kwargs={"door_id": door.id}), follow=True)
        self.assertEqual(response.status_code, 200)  # All good now
        self.assertTrue("farewell_screen" in response.request["PATH_INFO"])

    def test_login_to_area(self):
        response = self.client.post(reverse("login_to_area", kwargs={"door_id": door.id}), follow=True)
        test_response_is_failed_login(self, response)
        login_as_user(self.client)
        response = self.client.post(reverse("login_to_area", kwargs={"door_id": door.id}), follow=True)
        test_response_is_landing_page(self, response)  # landing since we don't have the right credentials
        user = login_as_user_with_permissions(self.client, ["add_areaaccessrecord"])
        response = self.client.get(
            reverse("login_to_area", kwargs={"door_id": door.id}), data={"badge_number": user.badge_number}, follow=True
        )
        self.assertEqual(response.status_code, 405)  # GET isn't accepted, only POST
        response = self.client.post(reverse("login_to_area", kwargs={"door_id": 999}), follow=True)
        self.assertEqual(response.status_code, 404)  # wrong door id
        response = self.client.post(reverse("login_to_area", kwargs={"door_id": door.id}), follow=True)
        self.assertContains(response, "Your badge wasn't recognized")
        response = self.client.post(
            reverse("login_to_area", kwargs={"door_id": door.id}), data={"badge_number": 999}, follow=True
        )
        self.assertContains(response, "Your badge wasn't recognized")
        response = self.client.post(
            reverse("login_to_area", kwargs={"door_id": door.id}), data={"badge_number": user.badge_number}, follow=True
        )
        self.assertTrue(f"login_to_area/{door.id}" in response.request["PATH_INFO"])
        self.assertContains(
            response=response, text="You are not a member of any active projects", status_code=200
        )  # user does not have active projects
        user.projects.add(Project.objects.create(name="Project1", account=Account.objects.create(name="Account1")))
        user.save()
        response = self.client.post(
            reverse("login_to_area", kwargs={"door_id": door.id}), data={"badge_number": user.badge_number}, follow=True
        )
        self.assertTrue(f"login_to_area/{door.id}" in response.request["PATH_INFO"])
        self.assertContains(
            response=response, text="Physical access denied", status_code=200
        )  # user does not have access
        area = door.areas.first()
        user.physical_access_levels.add(
            PhysicalAccessLevel.objects.create(
                name="cleanroom access", area=area, schedule=PhysicalAccessLevel.Schedule.ALWAYS
            )
        )
        user.save()
        area.maximum_capacity = 1
        area.save()
        # add a logged in person so capacity is reached
        AreaAccessRecord.objects.create(
            area=area,
            customer=User.objects.create(
                username="test_staff2", first_name="Test", last_name="Staff", is_staff=True, badge_number=2222
            ),
            project=Project.objects.get(name="Project1"),
            start=timezone.now(),
        )
        staff = User.objects.create(
            username="test_staff1", first_name="Test", last_name="Staff", is_staff=True, badge_number=11111
        )
        staff.projects.add(Project.objects.get(name="Project1"))
        staff.physical_access_levels.add(PhysicalAccessLevel.objects.get(name="cleanroom access"))
        staff.save()
        self.client.force_login(user=user)
        response = self.client.post(
            reverse("login_to_area", kwargs={"door_id": door.id}), data={"badge_number": user.badge_number}, follow=True
        )
        self.assertContains(response, f"The {area} has reached its maximum capacity.")
        # staff can still login
        response = self.client.post(
            reverse("login_to_area", kwargs={"door_id": door.id}),
            data={"badge_number": staff.badge_number},
            follow=True,
        )
        self.assertTrue(f"login_to_area/{door.id}" in response.request["PATH_INFO"])
        self.assertContains(response=response, text="You're logged in to the ", status_code=200)
        self.assertTrue(
            AreaAccessRecord.objects.filter(
                area=area, customer=User.objects.get(badge_number=staff.badge_number)
            ).exists()
        )
        # try again user, should fail
        response = self.client.post(
            reverse("login_to_area", kwargs={"door_id": door.id}), data={"badge_number": user.badge_number}, follow=True
        )
        self.assertContains(response, f"The {area} has reached its maximum capacity.")
        # increase capacity so user can login
        area.maximum_capacity = 5
        area.save()
        response = self.client.post(
            reverse("login_to_area", kwargs={"door_id": door.id}), data={"badge_number": user.badge_number}, follow=True
        )
        self.assertTrue(f"login_to_area/{door.id}" in response.request["PATH_INFO"])
        self.assertContains(response=response, text="You're logged in to the ", status_code=200)
        self.assertTrue(
            AreaAccessRecord.objects.filter(
                area=area, customer=User.objects.get(badge_number=user.badge_number)
            ).exists()
        )

    def test_staff_login_to_area(self):
        staff = login_as_staff(self.client)
        tablet_user = login_as_user_with_permissions(self.client, ["add_areaaccessrecord"])
        response = self.client.post(
            reverse("login_to_area", kwargs={"door_id": door.id}),
            data={"badge_number": staff.badge_number},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            "You are not a member of any active projects" in str(response.content)
        )  # user does not have active projects
        staff.projects.add(
            Project.objects.create(name="Maintenance", account=Account.objects.create(name="Maintenance Account"))
        )
        staff.save()
        response = self.client.post(
            reverse("login_to_area", kwargs={"door_id": door.id}),
            data={"badge_number": staff.badge_number},
            follow=True,
        )
        self.assertTrue("Physical access denied" in str(response.content))
        # create an area an allow staff access without granting it to them
        area = door.areas.first()
        access = PhysicalAccessLevel.objects.create(
            allow_staff_access=True,
            name="cleanroom access",
            area=area,
            schedule=PhysicalAccessLevel.Schedule.ALWAYS,
        )
        response = self.client.post(
            reverse("login_to_area", kwargs={"door_id": door.id}),
            data={"badge_number": staff.badge_number},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(f"login_to_area/{door.id}" in response.request["PATH_INFO"])
        self.assertTrue("You're logged in to the " in str(response.content))
        # try to login again
        response = self.client.post(
            reverse("login_to_area", kwargs={"door_id": door.id}),
            data={"badge_number": staff.badge_number},
            follow=True,
        )
        self.assertTrue("already logged in the" in str(response.content))  # user already logged in
        response = self.client.post(
            reverse("logout_of_area", kwargs={"door_id": door.id}),
            data={"badge_number": staff.badge_number},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        test_response_is_landing_page(self, response)  # tablet user does not have permission to logout
        tablet_user.user_permissions.add(Permission.objects.get(codename="change_areaaccessrecord"))
        tablet_user.save()
        response = self.client.post(
            reverse("logout_of_area", kwargs={"door_id": door.id}),
            data={"badge_number": staff.badge_number},
            follow=True,
        )
        self.assertTrue("now logged out of the" in str(response.content))
        # now undo access and try explicitly
        access.allow_staff_access = False
        access.save()
        response = self.client.post(
            reverse("login_to_area", kwargs={"door_id": door.id}),
            data={"badge_number": staff.badge_number},
            follow=True,
        )
        self.assertTrue("Physical access denied" in str(response.content))
        # also work by explicitly giving access to staff
        staff.physical_access_levels.add(access)
        staff.save()
        response = self.client.post(
            reverse("login_to_area", kwargs={"door_id": door.id}),
            data={"badge_number": staff.badge_number},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(f"login_to_area/{door.id}" in response.request["PATH_INFO"])
        self.assertTrue("You're logged in to the " in str(response.content))
        self.assertTrue(
            AreaAccessRecord.objects.filter(
                area=area, customer=User.objects.get(badge_number=staff.badge_number), end__isnull=True
            ).exists()
        )


class SelfLoginAreaAccessTestCase(TestCase):
    area: Area = None

    def setUp(self):
        global area
        interlock_card_category = InterlockCardCategory.objects.get(key="stanford")
        interlock_card = InterlockCard.objects.create(
            server="server.com", port=80, number=1, even_port=1, odd_port=2, category=interlock_card_category
        )
        interlock = Interlock.objects.create(card=interlock_card, channel=1)
        area = Area.objects.create(name="Cleanroom")
        door = Door.objects.create(name="test_door", interlock=interlock)
        door.areas.set([area])

    def test_login_to_area(self):
        self.client.post(reverse("self_log_in"), data={"area": area.id}, follow=True)
        self.assertFalse(AreaAccessRecord.objects.filter(area=area, end__isnull=True).exists())
        user = login_as_user(self.client)
        self.client.post(reverse("self_log_in"), data={"area": area.id}, follow=True)
        self.assertFalse(AreaAccessRecord.objects.filter(area=area, end__isnull=True).exists())
        Customization.objects.update_or_create(name="self_log_in", defaults={"value": "enabled"})
        self.assertFalse(AreaAccessRecord.objects.filter(area=area, end__isnull=True).exists())
        project = Project.objects.create(name="Project1", account=Account.objects.create(name="Account1"))
        user.projects.add(project)
        user.save()
        self.client.post(reverse("self_log_in"), data={"area": area.id, "project": project.id}, follow=True)
        self.assertFalse(
            AreaAccessRecord.objects.filter(area=area, end__isnull=True).exists()
        )  # user doesn't have access
        user.physical_access_levels.add(
            PhysicalAccessLevel.objects.create(
                name="cleanroom access", area=area, schedule=PhysicalAccessLevel.Schedule.ALWAYS
            )
        )
        user.save()
        self.client.post(reverse("self_log_in"), data={"area": area.id, "project": project.id}, follow=True)
        self.assertTrue(AreaAccessRecord.objects.filter(area=area, customer=user, end__isnull=True).exists())

    def test_staff_login_to_area(self):
        staff = login_as_staff(self.client)
        self.client.post(reverse("self_log_in"), data={"area": area.id}, follow=True)
        self.assertFalse(AreaAccessRecord.objects.filter(area=area, end__isnull=True).exists())
        # user does not have active projects
        project = Project.objects.create(name="Maintenance", account=Account.objects.create(name="Maintenance Account"))
        staff.projects.add(project)
        staff.save()
        self.client.post(reverse("self_log_in"), data={"area": area.id, "project": project.id}, follow=True)
        self.assertFalse(AreaAccessRecord.objects.filter(area=area, end__isnull=True).exists())
        Customization.objects.update_or_create(name="self_log_in", defaults={"value": "enabled"})
        self.client.post(reverse("self_log_in"), data={"area": area.id, "project": project.id}, follow=True)
        self.assertFalse(AreaAccessRecord.objects.filter(area=area, end__isnull=True).exists())
        # create an area an allow staff access without granting it to them
        access = PhysicalAccessLevel.objects.create(
            allow_staff_access=True, name="cleanroom access", area=area, schedule=PhysicalAccessLevel.Schedule.ALWAYS
        )
        self.client.post(reverse("self_log_in"), data={"area": area.id, "project": project.id}, follow=True)
        record = AreaAccessRecord.objects.filter(area=area, customer=staff)
        self.assertTrue(record.exists())
        # try to login again
        self.client.post(reverse("self_log_in"), data={"area": area.id, "project": project.id}, follow=True)
        # not successful. still only one record
        self.assertEqual(AreaAccessRecord.objects.filter(area=area, customer=staff, end__isnull=True).count(), 1)
        self.assertEqual(AreaAccessRecord.objects.filter(area=area, customer=staff, end__isnull=True)[0], record[0])
        self.assertTrue(record[0].end is None)
        # logout
        Customization.objects.update_or_create(name="self_log_out", defaults={"value": "enabled"})
        self.client.get(reverse("self_log_out", kwargs={"user_id": staff.id}), follow=True)
        self.assertTrue(record[0].end is not None)
        # now undo access and try explicitly
        access.allow_staff_access = False
        access.save()
        self.client.post(reverse("self_log_in"), data={"area": area.id, "project": project.id}, follow=True)
        self.assertFalse(AreaAccessRecord.objects.filter(area=area, customer=staff, end__isnull=True).exists())
        # also work by explicitly giving access to staff
        staff.physical_access_levels.add(access)
        staff.save()
        self.client.post(reverse("self_log_in"), data={"area": area.id, "project": project.id}, follow=True)
        self.assertTrue(AreaAccessRecord.objects.filter(area=area, customer=staff, end__isnull=True).exists())


class NewAreaAccessTestCase(TestCase):
    area: Area = None
    door: Door = None

    def setUp(self):
        global area, door
        interlock_card_category = InterlockCardCategory.objects.get(key="stanford")
        interlock_card = InterlockCard.objects.create(
            server="server.com", port=80, number=1, even_port=1, odd_port=2, category=interlock_card_category
        )
        interlock = Interlock.objects.create(card=interlock_card, channel=1)
        area = Area.objects.create(name="Cleanroom")
        door = Door.objects.create(name="test_door", interlock=interlock)
        door.areas.set([area])

    def test_new_area_record_get(self):
        user = login_as_user(self.client)
        response = self.client.get(reverse("new_area_access_record"), data={"customer": user.id}, follow=True)
        test_response_is_landing_page(self, response)
        staff = login_as_staff(self.client)
        user.is_active = False
        user.save()
        response = self.client.get(reverse("new_area_access_record"), data={"customer": user.id}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue("Oops! Something went wrong" in str(response.content))
        self.assertTrue("is inactive" in str(response.content))  # user is inactive
        user.is_active = True
        user.save()
        response = self.client.get(reverse("new_area_access_record"), data={"customer": user.id}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue("Oops! Something went wrong" in str(response.content))
        self.assertTrue(
            "does not have any active projects to bill area access" in str(response.content)
        )  # user does not have active projects
        user.projects.add(Project.objects.create(name="Project1", account=Account.objects.create(name="Account1")))
        user.save()
        response = self.client.get(reverse("new_area_access_record"), data={"customer": user.id}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue("Oops! Something went wrong" in str(response.content))
        self.assertTrue(
            "does not have access to any billable areas" in str(response.content)
        )  # user does not have access
        user.physical_access_levels.add(
            PhysicalAccessLevel.objects.create(
                name="cleanroom access", area=area, schedule=PhysicalAccessLevel.Schedule.ALWAYS
            )
        )
        user.save()
        response = self.client.get(reverse("new_area_access_record"), data={"customer": user.id}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse("Oops! Something went wrong" in str(response.content))

    def test_new_area_record_post(self):
        project = Project.objects.create(name="Project1", account=Account.objects.create(name="Account1"))
        user = login_as_user(self.client)
        response = self.client.post(
            reverse("new_area_access_record"),
            data={"customer": user.id, "area": area.id, "project": project.id},
            follow=True,
        )
        test_response_is_landing_page(self, response)
        staff = login_as_staff(self.client)
        user.is_active = False
        user.save()
        response = self.client.post(
            reverse("new_area_access_record"),
            data={"customer": user.id, "area": area.id, "project": project.id},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue("Oops! Something went wrong" in str(response.content))
        self.assertTrue("is inactive" in str(response.content))  # user is inactive
        user.is_active = True
        user.save()
        response = self.client.post(
            reverse("new_area_access_record"),
            data={"customer": user.id, "area": area.id, "project": project.id},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue("Oops! Something went wrong" in str(response.content))
        self.assertTrue(
            "does not have any active projects to bill area access" in str(response.content)
        )  # user does not have active projects
        user.projects.add(project)
        user.save()
        response = self.client.post(
            reverse("new_area_access_record"),
            data={"customer": user.id, "area": area.id, "project": project.id},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue("Oops! Something went wrong" in str(response.content))
        self.assertTrue(
            "does not have access to any billable areas" in str(response.content)
        )  # user does not have access
        user.physical_access_levels.add(
            PhysicalAccessLevel.objects.create(
                name="cleanroom access", area=area, schedule=PhysicalAccessLevel.Schedule.ALWAYS
            )
        )
        user.save()
        response = self.client.post(
            reverse("new_area_access_record"),
            data={"customer": user.id, "area": area.id, "project": project.id},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse("Oops! Something went wrong" in str(response.content))
        self.assertTrue(AreaAccessRecord.objects.filter(area=area, customer=user, end__isnull=True).exists())

    def test_staff_login_to_area(self):
        staff = login_as_staff(self.client)
        tablet_user = login_as_user_with_permissions(self.client, ["add_areaaccessrecord"])
        response = self.client.post(
            reverse("login_to_area", kwargs={"door_id": door.id}),
            data={"badge_number": staff.badge_number},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            "You are not a member of any active projects" in str(response.content)
        )  # user does not have active projects
        staff.projects.add(
            Project.objects.create(name="Maintenance", account=Account.objects.create(name="Maintenance Account"))
        )
        staff.save()
        response = self.client.post(
            reverse("login_to_area", kwargs={"door_id": door.id}),
            data={"badge_number": staff.badge_number},
            follow=True,
        )
        self.assertTrue("Physical access denied" in str(response.content))
        # create an area an allow staff access without granting it to them
        access = PhysicalAccessLevel.objects.create(
            allow_staff_access=True,
            name="cleanroom access",
            area=area,
            schedule=PhysicalAccessLevel.Schedule.ALWAYS,
        )
        response = self.client.post(
            reverse("login_to_area", kwargs={"door_id": door.id}),
            data={"badge_number": staff.badge_number},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(f"login_to_area/{door.id}" in response.request["PATH_INFO"])
        self.assertTrue("You're logged in to the " in str(response.content))
        # try to login again
        response = self.client.post(
            reverse("login_to_area", kwargs={"door_id": door.id}),
            data={"badge_number": staff.badge_number},
            follow=True,
        )
        self.assertTrue("already logged in the" in str(response.content))  # user already logged in
        response = self.client.post(
            reverse("logout_of_area", kwargs={"door_id": door.id}),
            data={"badge_number": staff.badge_number},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        test_response_is_landing_page(self, response)  # tablet user does not have permission to logout
        tablet_user.user_permissions.add(Permission.objects.get(codename="change_areaaccessrecord"))
        tablet_user.save()
        response = self.client.post(
            reverse("logout_of_area", kwargs={"door_id": door.id}),
            data={"badge_number": staff.badge_number},
            follow=True,
        )
        self.assertTrue("now logged out of the" in str(response.content))
        # now undo access and try explicitly
        access.allow_staff_access = False
        access.save()
        response = self.client.post(
            reverse("login_to_area", kwargs={"door_id": door.id}),
            data={"badge_number": staff.badge_number},
            follow=True,
        )
        self.assertTrue("Physical access denied" in str(response.content))
        # also work by explicitly giving access to staff
        staff.physical_access_levels.add(access)
        staff.save()
        response = self.client.post(
            reverse("login_to_area", kwargs={"door_id": door.id}),
            data={"badge_number": staff.badge_number},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(f"login_to_area/{door.id}" in response.request["PATH_INFO"])
        self.assertTrue("You're logged in to the " in str(response.content))
        self.assertTrue(
            AreaAccessRecord.objects.filter(
                area=area, customer=User.objects.get(badge_number=staff.badge_number)
            ).exists()
        )

    def test_area_already_logged_in(self):
        user, project = create_user_and_project()
        record = AreaAccessRecord(customer=user, project=project, area=area, start=timezone.now())
        record.save()
        record_2 = AreaAccessRecord(customer=user, project=project, area=area, start=timezone.now())
        self.assertRaises(ValidationError, record_2.full_clean)


class DoorInterlockTestCase(TestCase):
    door: Door = None
    interlock: Interlock = None

    def setUp(self):
        global door, interlock
        interlock_card_category = InterlockCardCategory.objects.get(key="stanford")
        interlock_card = InterlockCard.objects.create(
            server="server.com", port=80, number=1, even_port=1, odd_port=2, category=interlock_card_category
        )
        interlock = Interlock.objects.create(card=interlock_card, channel=1)
        area = Area.objects.create(name="Test Area")
        door = Door.objects.create(name="test_door", interlock=interlock)
        door.areas.set([area])

    def test_door(self):
        self.assertEqual(door.interlock.state, Interlock.State.UNKNOWN)
        # unlocking door is an async action and creates problems when testing with SQLite (Database Table locked)


class AreaAutoLogoutTestCase(TestCase):
    def testAutoLogout(self):
        user = login_as_user(self.client)
        area = Area.objects.create(name="Cleanroom")
        project = Project.objects.create(name="Project1", account=Account.objects.create(name="Account1"))
        start = timezone.now() - datetime.timedelta(minutes=5)
        record = AreaAccessRecord.objects.create(area=area, customer=user, project=project, start=start)
        call_command("area_auto_logout_users")
        # Nothing should happen
        self.assertFalse(AreaAccessRecord.objects.get(id=record.id).end)
        area.auto_logout_time = 10
        area.save()
        call_command("area_auto_logout_users")
        # Nothing should happen
        self.assertFalse(AreaAccessRecord.objects.get(id=record.id).end)
        area.auto_logout_time = 3
        area.save()
        call_command("area_auto_logout_users")
        new_record = AreaAccessRecord.objects.get(id=record.id)
        self.assertEqual(new_record.end, new_record.start + datetime.timedelta(minutes=3))
