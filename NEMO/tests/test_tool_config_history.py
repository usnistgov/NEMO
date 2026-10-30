from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from NEMO.models import Configuration, ConfigurationHistory, Tool, User
from NEMO.tests.test_utilities import NEMOTestCaseMixin, create_user_and_project


class ToolConfigHistoryTestCase(NEMOTestCaseMixin, TestCase):
    def setUp(self):
        self.user, self.project = create_user_and_project()
        self.user.training_required = False
        self.user.save()

        self.operator = User.objects.create(
            username="operator_user",
            first_name="Jane",
            last_name="Doe",
            is_staff=True,
        )

        self.tool = Tool.objects.create(
            name="Test Etcher",
            _operational=True,
            _category="Etch",
            visible=True,
        )

        self.config = Configuration.objects.create(
            tool=self.tool,
            name="MFC Gas",
            configurable_item_name="MFC",
            available_settings="Argon, Oxygen, CF4",
            current_settings="Argon, Oxygen",
            advance_notice_limit=0,
            display_order=1,
        )

    def test_tool_config_history_empty(self):
        self.login_as(self.user)
        url = reverse("tool_config_history", args=[self.tool.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "There is no configuration history for this tool.")
        self.assertNotContains(response, "<table")

    def test_tool_config_history_table_view(self):
        self.login_as(self.user)

        # Create history records
        time1 = timezone.now()
        hist1 = ConfigurationHistory.objects.create(
            configuration=self.config,
            user=self.operator,
            item_name="MFC #1",
            slot=0,
            setting="Oxygen",
            modification_time=time1,
        )

        url = reverse("tool_config_history", args=[self.tool.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # Verify headers
        self.assertContains(response, "<th>Date</th>")
        self.assertContains(response, "<th>Operator</th>")
        self.assertContains(response, "<th>Configuration change</th>")

        # Verify export button (not shown) and pagination (shown)
        self.assertNotContains(response, f"tool_config_history/{self.tool.id}/?csv=true")
        self.assertNotContains(response, "Export")
        self.assertContains(response, "results per page")

        # Verify row content
        self.assertRegex(response.content.decode(), r"MFC #1:\s+ Oxygen")
        self.assertContains(response, str(self.operator))

        # Staff can see export button
        self.login_as_staff()
        url = reverse("tool_config_history", args=[self.tool.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"tool_config_history/{self.tool.id}/?csv=true")
        self.assertContains(response, "Export")

    def test_tool_config_history_pagination(self):
        self.login_as(self.user)

        # Create 30 history records
        base_time = timezone.now()
        for i in range(30):
            ConfigurationHistory.objects.create(
                configuration=self.config,
                user=self.operator,
                item_name="MFC #1",
                slot=0,
                setting=f"Setting_{i}",
                modification_time=base_time + timezone.timedelta(minutes=i),
            )

        url = reverse("tool_config_history", args=[self.tool.id])

        # Page 1 default: 25 items
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["page"]), 25)
        self.assertContains(response, "Page 1 of 2")
        self.assertContains(response, "Setting_29")  # Most recent
        self.assertNotContains(response, "Setting_4")  # On page 2

        # Page 2: remaining 5 items
        response_p2 = self.client.get(url, {"p": 2})
        self.assertEqual(response_p2.status_code, 200)
        self.assertEqual(len(response_p2.context["page"]), 5)
        self.assertContains(response_p2, "Page 2 of 2")
        self.assertContains(response_p2, "Setting_4")
        self.assertNotContains(response_p2, "Setting_29")

        # Custom per_page = 10
        response_pp = self.client.get(url, {"pp": 10})
        self.assertEqual(response_pp.status_code, 200)
        self.assertEqual(len(response_pp.context["page"]), 10)
        self.assertContains(response_pp, "Page 1 of 3")

    def test_tool_config_history_csv_export(self):
        self.login_as_staff()

        time1 = timezone.now()
        ConfigurationHistory.objects.create(
            configuration=self.config,
            user=self.operator,
            item_name="MFC #1",
            slot=0,
            setting="Oxygen",
            modification_time=time1,
        )

        url = reverse("tool_config_history", args=[self.tool.id])
        response = self.client.get(url, {"csv": "true"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv")
        self.assertIn("attachment; filename=", response["Content-Disposition"])
        self.assertIn("tool_configuration_history_test_etcher_", response["Content-Disposition"])

        content = response.content.decode()
        lines = [line.strip() for line in content.strip().split("\r\n") if line.strip()]
        if len(lines) <= 1:
            lines = [line.strip() for line in content.strip().split("\n") if line.strip()]

        # Header check
        self.assertEqual(lines[0], "Date,Operator,Configuration,Setting")

        # Rows check
        self.assertTrue(any("MFC #1" in line for line in lines[1:]))
        self.assertTrue(any("Oxygen" in line for line in lines[1:]))
        self.assertTrue(any(str(self.operator) in line for line in lines[1:]))
