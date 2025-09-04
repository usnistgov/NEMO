from datetime import timedelta
from typing import Optional

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from NEMO.admin import InterlockCardAdminForm, ToolAdminForm
from NEMO.models import (
    Account,
    Area,
    AreaAccessRecord,
    Door,
    Interlock,
    InterlockCardCategory,
    PhysicalAccessLevel,
    Project,
    Tool,
    UsageEvent,
    User,
)
from NEMO.tests.test_utilities import NEMOTestCaseMixin, create_user_and_project

tool: Optional[Tool] = None
alternate_tool: Optional[Tool] = None
area_door: Optional[Door] = None


class ToolTestCase(NEMOTestCaseMixin, TestCase):
    def setUp(self):
        # This also tests the admin forms for interlock card and tool
        global tool, alternate_tool, area_door
        interlock_category = InterlockCardCategory.objects.get(key="web_relay_http")
        interlock_card_data = {"server": "example.com", "port": 25, "category": interlock_category.id}
        interlock_card_form = InterlockCardAdminForm(interlock_card_data)
        self.assertTrue(interlock_card_form.is_valid(), interlock_card_form.errors.as_text())
        interlock_card = interlock_card_form.save()
        interlock = Interlock.objects.create(card=interlock_card, channel=1)
        cleanroom_interlock = Interlock.objects.create(card=interlock_card, channel=2)
        owner = User.objects.create(username="mctest", first_name="Testy", last_name="McTester")
        cleanroom = Area.objects.create(name="cleanroom")
        tool_data = {
            "name": "test_tool",
            "_category": "test",
            "_location": "office",
            "_phone_number": "1234567890",
            "_primary_owner": owner.id,
            "_backup_owners": [owner.id],
            "_interlock": interlock.id,
            "_operational": False,
            "_notification_email_address": "email@example.com",
            "_requires_area_access": cleanroom.id,
            "_grant_badge_reader_access_upon_qualification": "test",
            "_grant_physical_access_level_upon_qualification": PhysicalAccessLevel.objects.create(
                name="cleanroom access", schedule=PhysicalAccessLevel.Schedule.ALWAYS, area=cleanroom
            ).id,
            "_reservation_horizon": 15,
            "_minimum_usage_block_time": 3,
            "_maximum_usage_block_time": 7,
            "_maximum_reservations_per_day": 2,
            "_minimum_time_between_reservations": 10,
            "_maximum_future_reservation_time": 20,
            "_missed_reservation_threshold": 30,
            "_max_delayed_logoff": 120,
            "_post_usage_questions": '[{"type": "textbox", "name": "question_name", "title": "question_title", "max-width": "100%"}]',
            "_policy_off_between_times": True,
            "_policy_off_start_time": "5:00 PM",
            "_policy_off_end_time": "4:00 PM",
            "_policy_off_weekend": True,
            "visible": True,
            "_operation_mode": Tool.OperationMode.REGULAR,
            "_properties": "{}",
        }
        area_door = Door.objects.create(name="cleanroom door", interlock=cleanroom_interlock)
        area_door.areas.set([cleanroom])
        tool_form = ToolAdminForm(tool_data)
        self.assertTrue(tool_form.is_valid(), tool_form.errors.as_text())
        tool = tool_form.save()
        alternate_tool_data = {
            "name": "alt_test_tool",
            "parent_tool": tool.id,
            "visible": True,
            "_operation_mode": Tool.OperationMode.REGULAR,
            "_properties": "{}",
        }
        alternate_tool_form = ToolAdminForm(alternate_tool_data)
        self.assertTrue(alternate_tool_form.is_valid(), alternate_tool_form.errors.as_text())
        alternate_tool = alternate_tool_form.save()

    def test_tool_and_parent_properties(self):
        self.assertNotEqual(tool.id, alternate_tool.id)
        self.assertNotEqual(tool.name, alternate_tool.name)
        self.assertFalse(alternate_tool.visible)
        self.assertTrue(tool.visible)
        self.assertTrue(tool.is_parent_tool())
        self.assertTrue(alternate_tool.is_child_tool())
        self.assertEqual(tool.category, alternate_tool.category)
        self.assertEqual(tool.operational, alternate_tool.operational)
        self.assertEqual(tool.primary_owner, alternate_tool.primary_owner)
        self.assertEqual(tool.backup_owners, alternate_tool.backup_owners)
        self.assertEqual(tool.location, alternate_tool.location)
        self.assertEqual(tool.phone_number, alternate_tool.phone_number)
        self.assertEqual(tool.notification_email_address, alternate_tool.notification_email_address)
        self.assertEqual(tool.interlock, alternate_tool.interlock)
        self.assertEqual(tool.requires_area_access, alternate_tool.requires_area_access)
        self.assertEqual(
            tool.grant_physical_access_level_upon_qualification,
            alternate_tool.grant_physical_access_level_upon_qualification,
        )
        self.assertEqual(
            tool.grant_badge_reader_access_upon_qualification,
            alternate_tool.grant_badge_reader_access_upon_qualification,
        )
        self.assertEqual(tool.reservation_horizon, alternate_tool.reservation_horizon)
        self.assertEqual(tool.minimum_usage_block_time, alternate_tool.minimum_usage_block_time)
        self.assertEqual(tool.maximum_usage_block_time, alternate_tool.maximum_usage_block_time)
        self.assertEqual(tool.maximum_reservations_per_day, alternate_tool.maximum_reservations_per_day)
        self.assertEqual(tool.minimum_time_between_reservations, alternate_tool.minimum_time_between_reservations)
        self.assertEqual(tool.maximum_future_reservation_time, alternate_tool.maximum_future_reservation_time)
        self.assertEqual(tool.missed_reservation_threshold, alternate_tool.missed_reservation_threshold)
        self.assertEqual(tool.max_delayed_logoff, alternate_tool.max_delayed_logoff)
        self.assertEqual(tool.post_usage_questions, alternate_tool.post_usage_questions)
        self.assertEqual(tool.policy_off_between_times, alternate_tool.policy_off_between_times)
        self.assertEqual(tool.policy_off_start_time, alternate_tool.policy_off_start_time)
        self.assertEqual(tool.policy_off_end_time, alternate_tool.policy_off_end_time)
        self.assertEqual(tool.policy_off_weekend, alternate_tool.policy_off_weekend)

        self.assertEqual(tool.get_absolute_url(), alternate_tool.get_absolute_url())

    def test_enable_tool_policy(self):
        tool.operational = True
        tool.save()
        user = User.objects.create(
            username="noproj",
            first_name="scott",
            last_name="NoProj",
            access_expiration=timezone.now() - timedelta(days=10),
        )
        project = Project.objects.create(name="test_prj", account=Account.objects.create(name="test_acct"))

        self.login_as(user)

        response = self.client.post(reverse("enable_tool", args=[tool.id, user.id, project.id, "false"]), follow=True)
        self.assertContains(response, "You are not qualified to use this tool.", status_code=400)

        user.qualifications.add(tool)
        self.login_as(user)
        response = self.client.post(reverse("enable_tool", args=[tool.id, user.id, project.id, "false"]), follow=True)
        self.assertContains(
            response,
            f"You must be logged in to the {tool.requires_area_access.name} to operate this tool.",
            status_code=400,
        )

        AreaAccessRecord.objects.create(
            area=tool.requires_area_access, customer=user, project=project, start=timezone.now()
        )
        self.login_as(user)
        response = self.client.post(reverse("enable_tool", args=[tool.id, user.id, project.id, "false"]), follow=True)
        self.assertContains(response, f"Permission to bill project {project.name} was denied.", status_code=400)

        user.projects.add(project)
        self.login_as(user)
        response = self.client.post(reverse("enable_tool", args=[tool.id, user.id, project.id, "false"]), follow=True)
        self.assertContains(
            response,
            "You are blocked from using all tools in the Facility. Please complete the Facility rules tutorial in order to use tools.",
            status_code=400,
        )

        user.training_required = False
        user.save()
        self.login_as(user)
        response = self.client.post(reverse("enable_tool", args=[tool.id, user.id, project.id, "false"]), follow=True)
        self.assertContains(response, "Your NEMO access has expired.", status_code=400)

        user.access_expiration = None
        user.save()
        self.login_as(user)
        response = self.client.post(reverse("enable_tool", args=[tool.id, user.id, project.id, "false"]), follow=True)
        self.assertEqual(response.status_code, 200)

    def test_tool_in_use(self):
        user, project = create_user_and_project(add_area_access_permissions=True)
        # make the tool operational
        tool.operational = True
        tool.save()
        # user needs to be qualified to use the tool
        user.qualifications.add(tool)
        user.physical_access_levels.add(PhysicalAccessLevel.objects.get(name="cleanroom access"))
        user.badge_number = 11
        user.training_required = False
        user.save()
        # log into the area
        self.login_as(user)
        response = self.client.post(
            reverse("login_to_area", kwargs={"door_id": area_door.id}), {"badge_number": user.badge_number}, follow=True
        )
        self.assertEqual(response.status_code, 200, response.content.decode())
        self.login_as(user)
        # start using tool
        response = self.client.post(
            reverse(
                "enable_tool",
                kwargs={"tool_id": tool.id, "user_id": user.id, "project_id": project.id, "staff_charge": "false"},
            ),
            follow=True,
        )
        self.assertEqual(response.status_code, 200, response.content.decode())
        # make sure both tool and child tool are "in use"
        self.assertTrue(tool.in_use())
        self.assertTrue(alternate_tool.in_use())
        # make sure both return the same usage event
        self.assertEqual(tool.get_current_usage_event(), alternate_tool.get_current_usage_event())

    def test_tool_already_in_use(self):
        user, project = create_user_and_project()
        usage = UsageEvent(user=user, operator=user, project=project, tool=tool, start=timezone.now())
        usage.save()
        usage_2 = UsageEvent(user=user, operator=user, project=project, tool=tool, start=timezone.now())
        self.assertRaises(ValidationError, usage_2.full_clean)
