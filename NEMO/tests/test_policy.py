from datetime import timedelta

from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from NEMO.exceptions import NotAllowedToChargeProjectException, UserAccessError
from NEMO.models import (
    Area,
    PhysicalAccessLevel,
    Qualification,
    Reservation,
    ScheduledOutage,
    Tool,
    ToolQualificationGroup,
    TrainingSession,
    UsageEvent,
    User,
)
from NEMO.policy import policy_class as policy
from NEMO.tests.test_utilities import NEMOTestCaseMixin, create_user_and_project


class PolicyPermissionsTestCase(NEMOTestCaseMixin, TestCase):
    def setUp(self):
        self.user, self.project = create_user_and_project()
        self.user.training_required = False
        self.user.save()

        self.area = Area.objects.create(name="Policy Test Area")
        self.access_level = PhysicalAccessLevel.objects.create(
            name="All Access", area=self.area, schedule=PhysicalAccessLevel.Schedule.ALWAYS
        )
        self.user.physical_access_levels.add(self.access_level)

        self.tool = Tool.objects.create(
            name="Policy Test Tool",
            _operational=True,
            _category="General",
            visible=True,
        )
        self.user.qualifications.add(self.tool)

    def _add_permission(self, user: User, model: str, codename: str) -> User:
        from django.contrib.contenttypes.models import ContentType

        content_type, _ = ContentType.objects.get_or_create(app_label="NEMO", model=model)
        perm, _ = Permission.objects.get_or_create(
            codename=codename,
            content_type=content_type,
            defaults={"name": codename},
        )
        user.user_permissions.add(perm)
        for attr in ["_perm_cache", "_user_perm_cache", "_group_perm_cache"]:
            if hasattr(user, attr):
                delattr(user, attr)
        return user

    def _remove_permission(self, user: User, codename: str) -> User:
        user.user_permissions.remove(Permission.objects.get(codename=codename))
        for attr in ["_perm_cache", "_user_perm_cache", "_group_perm_cache"]:
            if hasattr(user, attr):
                delattr(user, attr)
        return user

    def test_block_enable_tools_permission(self):
        # Without permission, enabling tool should succeed (status 200)
        response = policy.check_to_enable_tool(
            tool=self.tool,
            operator=self.user,
            user=self.user,
            project=self.project,
            staff_charge=False,
        )
        self.assertEqual(response.status_code, 200)

        # With block_enable_tools permission, enabling tool should be blocked (status 400)
        self._add_permission(self.user, "policy", "block_enable_tools")
        response = policy.check_to_enable_tool(
            tool=self.tool,
            operator=self.user,
            user=self.user,
            project=self.project,
            staff_charge=False,
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.content.decode(), "You do not have permission to enable tools.")

        # Staff enabling tool on behalf of a user who has block_enable_tools permission
        staff, staff_project = create_user_and_project(is_staff=True)
        staff.training_required = False
        staff.save()
        response = policy.check_to_enable_tool(
            tool=self.tool,
            operator=staff,
            user=self.user,
            project=self.project,
            staff_charge=False,
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.content.decode(), f"{self.user} does not have permission to enable tools.")

    def test_block_create_reservations_permission(self):
        start = timezone.now() + timedelta(days=1)
        end = start + timedelta(hours=1)
        reservation = Reservation(
            tool=self.tool,
            user=self.user,
            creator=self.user,
            project=self.project,
            start=start,
            end=end,
            short_notice=False,
        )

        # Without permission, creating reservation should have no problems
        problems, overridable = policy.check_to_save_reservation(
            cancelled_reservation=None,
            new_reservation=reservation,
            user_creating_reservation=self.user,
            explicit_policy_override=False,
        )
        self.assertEqual(problems, [])

        # With block_create_reservations permission (user creating for themselves)
        self._add_permission(self.user, "policy", "block_create_reservations")
        problems, overridable = policy.check_to_save_reservation(
            cancelled_reservation=None,
            new_reservation=reservation,
            user_creating_reservation=self.user,
            explicit_policy_override=False,
        )
        self.assertEqual(problems, ["You do not have permission to create reservations."])
        self.assertTrue(overridable)

        # When creating for another user who has block_create_reservations permission
        other_user, other_project = create_user_and_project()
        other_user.training_required = False
        other_user.qualifications.add(self.tool)
        other_user.save()
        self._add_permission(other_user, "policy", "block_create_reservations")

        reservation_for_other = Reservation(
            tool=self.tool,
            user=other_user,
            creator=self.user,
            project=other_project,
            start=start,
            end=end,
            short_notice=False,
        )
        problems, overridable = policy.check_to_save_reservation(
            cancelled_reservation=None,
            new_reservation=reservation_for_other,
            user_creating_reservation=self.user,
            explicit_policy_override=False,
        )
        self.assertEqual(problems, [f"{other_user} does not have permission to create reservations."])
        self.assertTrue(overridable)

    def test_block_create_outages_permission(self):
        start = timezone.now() + timedelta(days=1)
        end = start + timedelta(hours=2)
        outage = ScheduledOutage(
            tool=self.tool,
            creator=self.user,
            start=start,
            end=end,
            title="Scheduled Maintenance",
        )

        # Without permission, creating outage should succeed (status 200)
        response = policy.check_to_create_outage(user=self.user, outage=outage)
        self.assertEqual(response.status_code, 200)

        # With block_create_outages permission, creating outage should fail (status 400)
        self._add_permission(self.user, "policy", "block_create_outages")
        response = policy.check_to_create_outage(user=self.user, outage=outage)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.content.decode(), "You do not have permission to create outages.")

    def test_block_enter_any_areas_permission(self):
        # Without permission, entering any area or specific area should succeed
        policy.check_to_enter_any_area(user=self.user)
        policy.check_to_enter_area(area=self.area, user=self.user)

        # With block_enter_any_areas permission
        self._add_permission(self.user, "policy", "block_enter_any_areas")

        with self.assertRaises(UserAccessError) as cm_any:
            policy.check_to_enter_any_area(user=self.user)
        self.assertIn("You do not have permission to enter any areas.", str(cm_any.exception))

        with self.assertRaises(UserAccessError) as cm_area:
            policy.check_to_enter_area(area=self.area, user=self.user)
        self.assertIn("You do not have permission to enter any areas.", str(cm_area.exception))

        # Staff user with block_enter_any_areas permission is also blocked
        staff, staff_project = create_user_and_project(is_staff=True)
        staff.training_required = False
        staff.save()
        self._add_permission(staff, "policy", "block_enter_any_areas")
        with self.assertRaises(UserAccessError) as cm_staff:
            policy.check_to_enter_area(area=self.area, user=staff)
        self.assertIn("You do not have permission to enter any areas.", str(cm_staff.exception))

    def test_block_bill_projects_permission(self):
        usage_event = UsageEvent(
            tool=self.tool,
            project=self.project,
            user=self.user,
            operator=self.user,
        )

        # Without permission, billing to project should succeed
        policy.check_billing_to_project(
            project=self.project,
            user=self.user,
            item=self.tool,
            charge=usage_event,
        )

        # With project=None, check_billing_to_project does not raise
        policy.check_billing_to_project(
            project=None,
            user=self.user,
            item=self.tool,
            charge=usage_event,
        )

        # With block_bill_projects permission, billing to project should raise exception
        self._add_permission(self.user, "policy", "block_bill_projects")

        with self.assertRaises(NotAllowedToChargeProjectException) as cm:
            policy.check_billing_to_project(
                project=self.project,
                user=self.user,
                item=self.tool,
                charge=usage_event,
            )
        self.assertEqual(cm.exception.msg, "You do not have permission to bill any projects")

    def test_block_qualify_on_tools_permission(self):
        # Without permission, qualifying user on tools should succeed (empty errors list)
        errors = policy.check_qualifying_user_on_tools(user=self.user, tools=[self.tool])
        self.assertEqual(errors, [])

        # With block_qualify_on_tools permission, qualifying user on tools should return error
        self._add_permission(self.user, "policy", "block_qualify_on_tools")
        errors = policy.check_qualifying_user_on_tools(user=self.user, tools=[self.tool])
        self.assertEqual(errors, [f"{self.user} is not allowed to be qualified on any tools."])

    def test_block_add_physical_access_levels_permission(self):
        # Without permission, adding physical access levels to user should succeed (empty errors list)
        errors = policy.check_adding_physical_access_levels_to_user(
            user=self.user, physical_access_levels=[self.access_level]
        )
        self.assertEqual(errors, [])

        # With block_add_physical_access_levels permission, adding physical access levels should return error
        self._add_permission(self.user, "policy", "block_add_physical_access_levels")
        errors = policy.check_adding_physical_access_levels_to_user(
            user=self.user, physical_access_levels=[self.access_level]
        )
        self.assertEqual(errors, [f"{self.user} is not allowed to have any physical access levels."])

    def test_qualify_via_api(self):
        staff = self.login_as_staff()
        self._add_permission(staff, "policy", "block_qualify_on_tools")
        for codename in ["add_qualification", "view_qualification", "delete_qualification"]:
            self._add_permission(staff, "qualification", codename)
        staff.save()

        user, user_project = create_user_and_project()
        tool = Tool.objects.create(name="API Qualification Tool", visible=True)

        url = reverse("qualification-list")

        # Blocked scenario: target user has block_qualify_on_tools permission
        self._add_permission(user, "policy", "block_qualify_on_tools")
        response = self.client.post(
            url,
            {"user": user.id, "tool": tool.id},
            content_type="application/json",
            follow=True,
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(f"{user} is not allowed to be qualified on any tools.", str(response.data))
        self.assertFalse(user.qualifications.filter(id=tool.id).exists())
        self.assertFalse(Qualification.objects.filter(user=user, tool=tool).exists())

        # Allowed scenario: remove block permission and qualify via API
        self._remove_permission(user, "block_qualify_on_tools")

        response = self.client.post(
            url,
            {"user": user.id, "tool": tool.id},
            content_type="application/json",
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(user.qualifications.filter(id=tool.id).exists())
        self.assertTrue(Qualification.objects.filter(user=user, tool=tool).exists())

    def test_qualify_via_training(self):
        trainer, trainer_project = create_user_and_project(is_staff=True)
        trainer.training_required = False
        trainer.save()
        self.login_as(trainer)

        trainee, trainee_project = create_user_and_project()
        trainee.training_required = False
        trainee.save()

        tool = Tool.objects.create(name="Training Qualification Tool", visible=True)

        charge_url = reverse("charge_training")
        post_data = {
            "chosen_user__0": trainee.id,
            "chosen_tool__0": tool.id,
            "chosen_type__0": "tool",
            "chosen_project__0": trainee_project.id,
            "duration__0": "60",
            "charge_type__0": str(TrainingSession.Type.INDIVIDUAL),
            "qualify__0": "on",
        }

        # Blocked scenario: trainee has block_qualify_on_tools permission
        self._add_permission(trainee, "policy", "block_qualify_on_tools")
        response = self.client.post(charge_url, post_data)
        self.assertEqual(response.status_code, 400)
        self.assertIn(f"{trainee} is not allowed to be qualified on any tools.", response.content.decode())
        self.assertFalse(trainee.qualifications.filter(id=tool.id).exists())
        self.assertFalse(TrainingSession.objects.filter(trainee=trainee, tool=tool).exists())

        # Allowed scenario: remove block permission and qualify via training
        self._remove_permission(trainee, "block_qualify_on_tools")

        response = self.client.post(charge_url, post_data)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(trainee.qualifications.filter(id=tool.id).exists())
        training_session = TrainingSession.objects.get(trainee=trainee, tool=tool)
        self.assertTrue(training_session.qualified)

        # Tool group qualification via training:
        tool2 = Tool.objects.create(name="Training Qual Tool 2", visible=True)
        tool_group = ToolQualificationGroup.objects.create(name="Group Qual", training_charge_tool=tool)
        tool_group.tools.add(tool, tool2)

        trainee2, trainee2_project = create_user_and_project()
        trainee2.training_required = False
        trainee2.save()

        group_post_data = {
            "chosen_user__0": trainee2.id,
            "chosen_tool__0": tool_group.id,
            "chosen_type__0": "group",
            "chosen_project__0": trainee2_project.id,
            "duration__0": "30",
            "charge_type__0": str(TrainingSession.Type.INDIVIDUAL),
            "qualify__0": "on",
        }

        # Blocked group training qualification
        self._add_permission(trainee2, "policy", "block_qualify_on_tools")
        response = self.client.post(charge_url, group_post_data)
        self.assertEqual(response.status_code, 400)
        self.assertIn(f"{trainee2} is not allowed to be qualified on any tools.", response.content.decode())
        self.assertFalse(trainee2.qualifications.filter(id=tool2.id).exists())

        # Allowed group training qualification
        self._remove_permission(trainee2, "block_qualify_on_tools")

        response = self.client.post(charge_url, group_post_data)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(trainee2.qualifications.filter(id=tool.id).exists())
        self.assertTrue(trainee2.qualifications.filter(id=tool2.id).exists())

    def test_qualify_via_modify_qualifications(self):
        trainer, trainer_project = create_user_and_project(is_staff=True)
        trainer.training_required = False
        trainer.save()
        self.login_as(trainer)

        trainee, trainee_project = create_user_and_project()
        trainee.training_required = False
        trainee.save()

        tool = Tool.objects.create(name="Training Qualification Tool", visible=True)

        qualifications_url = reverse("modify_qualifications")
        post_data = {"action": "qualify", "chosen_user[]": [trainee.id], "chosen_tool[]": [tool.id]}

        # Blocked scenario: trainee has block_qualify_on_tools permission
        self._add_permission(trainee, "policy", "block_qualify_on_tools")
        response = self.client.post(qualifications_url, post_data)
        self.assertEqual(response.status_code, 400)
        self.assertIn(f"{trainee} is not allowed to be qualified on any tools.", response.content.decode())
        self.assertFalse(trainee.qualifications.filter(id=tool.id).exists())
        self.assertFalse(TrainingSession.objects.filter(trainee=trainee, tool=tool).exists())

        # Allowed scenario: remove block permission and qualify via training
        self._remove_permission(trainee, "block_qualify_on_tools")

        response = self.client.post(qualifications_url, post_data)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(trainee.qualifications.filter(id=tool.id).exists())

        # Tool group qualification via training:
        tool2 = Tool.objects.create(name="Training Qual Tool 2", visible=True)
        tool_group = ToolQualificationGroup.objects.create(name="Group Qual", training_charge_tool=tool)
        tool_group.tools.add(tool, tool2)

        trainee2, trainee2_project = create_user_and_project()
        trainee2.training_required = False
        trainee2.save()

        group_post_data = {
            "action": "qualify",
            "chosen_user[]": [trainee2.id],
            "chosen_toolqualificationgroup[]": [tool_group.id],
        }

        # Blocked group training qualification
        self._add_permission(trainee2, "policy", "block_qualify_on_tools")
        response = self.client.post(qualifications_url, group_post_data, follow=True)
        self.assertEqual(response.status_code, 400)
        self.assertIn(f"{trainee2} is not allowed to be qualified on any tools.", response.content.decode())
        self.assertFalse(trainee2.qualifications.filter(id=tool2.id).exists())

        # Allowed group training qualification
        self._remove_permission(trainee2, "block_qualify_on_tools")

        response = self.client.post(qualifications_url, group_post_data)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(trainee2.qualifications.filter(id=tool.id).exists())
        self.assertTrue(trainee2.qualifications.filter(id=tool2.id).exists())
