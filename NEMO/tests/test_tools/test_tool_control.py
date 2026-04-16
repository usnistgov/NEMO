from django.test import TestCase
from django.urls import reverse

from NEMO.models import Account, Area, AreaAccessRecord, Customization, Project, StaffCharge, Tool, UsageEvent, User
from NEMO.tests.test_utilities import NEMOTestCaseMixin
from NEMO.views.customization import CustomizationBase


class ToolControlTestCase(NEMOTestCaseMixin, TestCase):
    def setUp(self):
        self.account = Account.objects.create(name="Test Account")
        self.project = Project.objects.create(name="Test Project", account=self.account)

        # Simple tool without area access requirement
        self.tool = Tool.objects.create(name="Test Tool", _operational=True, _category="Test")

        # Staff user (acts as operator in staff scenarios)
        self.staff = User.objects.create(
            username="staff_user",
            first_name="Staff",
            last_name="User",
            is_staff=True,
            training_required=False,
        )
        self.staff.projects.add(self.project)

        # Regular user (the one being used for in staff scenarios)
        self.user = User.objects.create(
            username="regular_user",
            first_name="Regular",
            last_name="User",
            training_required=False,
        )
        self.user.projects.add(self.project)
        self.user.qualifications.add(self.tool)

    def _enable_tool_url(self, tool, user, project, staff_charge):
        return reverse(
            "enable_tool",
            kwargs={
                "tool_id": tool.id,
                "user_id": user.id,
                "project_id": project.id,
                "staff_charge": "true" if staff_charge else "false",
            },
        )

    def _enable_tool_with_area(self):
        """Create a tool that requires area access, used for area-time tests."""
        area = Area.objects.create(name="Test Area")
        tool = Tool.objects.create(name="Area Tool", _operational=True, _requires_area_access=area)
        Customization.objects.update_or_create(
            name="tool_control_use_for_other_remote_area_access_automatically_enabled",
            defaults={"value": "enabled"},
        )
        CustomizationBase.invalidate_cache()
        return tool, area

    # --- Scenario 1: User using tool for their own project ---

    def test_user_self_usage(self):
        """User uses the tool for their own project (no staff charge, no remote work, no training)."""
        self.login_as(self.user)
        response = self.client.post(self._enable_tool_url(self.tool, self.user, self.project, False), follow=True)
        self.assertEqual(response.status_code, 200, response.content.decode())

        event = UsageEvent.objects.get(tool=self.tool)
        self.assertEqual(event.user, self.user)
        self.assertEqual(event.operator, self.user)
        self.assertEqual(event.project, self.project)
        self.assertIsNone(event.staff_charge)
        self.assertFalse(event.remote_work)
        self.assertFalse(event.training)
        self.assertIsNone(event.end)

    def test_user_charge_staff_time(self):
        """User uses the tool for staff charge"""
        self.login_as(self.user)
        response = self.client.post(self._enable_tool_url(self.tool, self.user, self.project, True), follow=True)
        self.assertEqual(response.status_code, 400, response.content.decode())

    # --- Scenario 2: Staff using tool for someone else (no charges) ---

    def test_staff_use_for_other_no_charge(self):
        """Staff uses the tool on behalf of another user with no staff charge or remote work."""
        self.login_as(self.staff)
        response = self.client.post(self._enable_tool_url(self.tool, self.user, self.project, False), follow=True)
        self.assertEqual(response.status_code, 200, response.content.decode())

        event = UsageEvent.objects.get(tool=self.tool)
        self.assertEqual(event.user, self.user)
        self.assertEqual(event.operator, self.staff)
        self.assertEqual(event.project, self.project)
        self.assertIsNone(event.staff_charge)
        self.assertFalse(event.remote_work)
        self.assertFalse(event.training)
        self.assertEqual(StaffCharge.objects.count(), 0)

    # --- Scenario 3: Staff using tool for someone else + charge staff time ---

    def test_staff_use_for_other_with_staff_charge(self):
        """Staff uses the tool on behalf of another user and charges staff time."""
        self.login_as(self.staff)
        response = self.client.post(self._enable_tool_url(self.tool, self.user, self.project, True), follow=True)
        self.assertEqual(response.status_code, 200, response.content.decode())

        event = UsageEvent.objects.get(tool=self.tool)
        self.assertEqual(event.user, self.user)
        self.assertEqual(event.operator, self.staff)
        self.assertIsNotNone(event.staff_charge)
        self.assertFalse(event.remote_work)
        self.assertFalse(event.training)

        staff_charge = StaffCharge.objects.get(staff_member=self.staff)
        self.assertEqual(staff_charge.customer, self.user)
        self.assertEqual(staff_charge.project, self.project)
        self.assertIsNone(staff_charge.end)
        self.assertEqual(AreaAccessRecord.objects.count(), 0)

    # --- Scenario 4: Staff using tool for someone else + charge staff time + area time ---

    def test_staff_use_for_other_with_staff_charge_and_area_time(self):
        """Staff uses the tool on behalf of another user, charges staff time, and area access is auto-created."""
        tool, area = self._enable_tool_with_area()
        self.login_as(self.staff)
        response = self.client.post(self._enable_tool_url(tool, self.user, self.project, True), follow=True)
        self.assertEqual(response.status_code, 200, response.content.decode())

        event = UsageEvent.objects.get(tool=tool)
        self.assertIsNotNone(event.staff_charge)
        self.assertFalse(event.remote_work)
        self.assertFalse(event.training)

        staff_charge = event.staff_charge
        self.assertEqual(staff_charge.customer, self.user)
        self.assertEqual(staff_charge.project, self.project)

        area_record = AreaAccessRecord.objects.get(staff_charge=staff_charge)
        self.assertEqual(area_record.area, area)
        self.assertEqual(area_record.customer, self.user)
        self.assertEqual(area_record.project, self.project)
        self.assertIsNone(area_record.end)

    # --- Scenario 5: Staff using tool for a remote project (no staff charge) ---

    def test_remote_project_no_staff_charge(self):
        """Staff uses the tool for a remote project with no staff charge."""
        self.login_as(self.staff)
        response = self.client.post(
            self._enable_tool_url(self.tool, self.user, self.project, False),
            {"remote_work": "true"},
            follow=True,
        )
        self.assertEqual(response.status_code, 200, response.content.decode())

        event = UsageEvent.objects.get(tool=self.tool)
        self.assertEqual(event.user, self.user)
        self.assertEqual(event.operator, self.staff)
        self.assertTrue(event.remote_work)
        self.assertIsNone(event.staff_charge)
        self.assertFalse(event.training)
        self.assertEqual(StaffCharge.objects.count(), 0)

    # --- Scenario 6: Staff using tool for a remote project + charge staff time ---

    def test_remote_project_with_staff_charge(self):
        """Staff uses the tool for a remote project and charges staff time."""
        self.login_as(self.staff)
        response = self.client.post(
            self._enable_tool_url(self.tool, self.user, self.project, True),
            {"remote_work": "true"},
            follow=True,
        )
        self.assertEqual(response.status_code, 200, response.content.decode())

        event = UsageEvent.objects.get(tool=self.tool)
        self.assertTrue(event.remote_work)
        self.assertIsNotNone(event.staff_charge)
        self.assertFalse(event.training)

        staff_charge = event.staff_charge
        self.assertEqual(staff_charge.customer, self.user)
        self.assertEqual(staff_charge.project, self.project)
        self.assertEqual(AreaAccessRecord.objects.count(), 0)

    # --- Scenario 7: Staff using tool for a remote project + charge staff time + area time ---

    def test_remote_project_with_staff_charge_and_area_time(self):
        """Staff uses the tool for a remote project, charges staff time, and area access is auto-created."""
        tool, area = self._enable_tool_with_area()
        self.login_as(self.staff)
        response = self.client.post(
            self._enable_tool_url(tool, self.user, self.project, True),
            {"remote_work": "true"},
            follow=True,
        )
        self.assertEqual(response.status_code, 200, response.content.decode())

        event = UsageEvent.objects.get(tool=tool)
        self.assertTrue(event.remote_work)
        self.assertIsNotNone(event.staff_charge)
        self.assertFalse(event.training)

        staff_charge = event.staff_charge
        area_record = AreaAccessRecord.objects.get(staff_charge=staff_charge)
        self.assertEqual(area_record.area, area)
        self.assertEqual(area_record.customer, self.user)
        self.assertEqual(area_record.project, self.project)
        self.assertIsNone(area_record.end)

    # --- Scenario 8: Staff member uses tool for their own training ---

    def test_training_for_self(self):
        """Staff member uses the tool to train themselves (operator == user, training flag set)."""
        self.login_as(self.staff)
        response = self.client.post(
            self._enable_tool_url(self.tool, self.staff, self.project, False),
            {"training": "true"},
            follow=True,
        )
        self.assertEqual(response.status_code, 200, response.content.decode())

        event = UsageEvent.objects.get(tool=self.tool)
        self.assertEqual(event.user, self.staff)
        self.assertEqual(event.operator, self.staff)
        self.assertTrue(event.training)
        self.assertIsNone(event.staff_charge)
        self.assertFalse(event.remote_work)

    # --- Scenario 9: Staff member uses tool to train another user ---

    def test_training_for_other(self):
        """Staff member uses the tool to train another user."""
        self.login_as(self.staff)
        response = self.client.post(
            self._enable_tool_url(self.tool, self.user, self.project, False),
            {"training": "true"},
            follow=True,
        )
        self.assertEqual(response.status_code, 200, response.content.decode())

        event = UsageEvent.objects.get(tool=self.tool)
        self.assertEqual(event.user, self.user)
        self.assertEqual(event.operator, self.staff)
        self.assertTrue(event.training)
        self.assertIsNone(event.staff_charge)
        self.assertFalse(event.remote_work)
