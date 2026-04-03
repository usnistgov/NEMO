from django.test import TestCase
from django.urls import reverse
from NEMO.models import SafetyCategory, SafetyItem, SafetyIssue, Chemical, ChemicalHazard, Customization
from NEMO.tests.test_utilities import NEMOTestCaseMixin, create_user_and_project
from NEMO.views.customization import CustomizationBase


class SafetyViewsTestCase(NEMOTestCaseMixin, TestCase):
    def setUp(self):
        self.user, self.project = create_user_and_project()
        self.staff_user, _ = create_user_and_project()
        self.staff_user.is_staff = True
        self.staff_user.save()

        # Enable all safety tabs
        Customization.objects.update_or_create(name="safety_show_safety", defaults={"value": "true"})
        Customization.objects.update_or_create(name="safety_show_safety_issues", defaults={"value": "true"})
        Customization.objects.update_or_create(name="safety_show_safety_data_sheets", defaults={"value": "true"})
        CustomizationBase.invalidate_cache()

    def test_safety_redirects(self):
        self.login_as(self.user)
        # Mock navigation_url to return a list item (as if SDS is enabled)
        from unittest.mock import patch

        with (
            patch("NEMO.views.safety.navigation_url", return_value="<li>SDS</li>"),
            patch("NEMO.views.safety.SafetyCustomization.get_bool") as mock_get_bool,
        ):
            # Case 1: safety_items_expand_categories = False
            # We must make sure it returns True for show_safety, show_safety_issues, show_safety_data_sheets
            # and False for safety_items_expand_categories
            mock_get_bool.side_effect = lambda x: False if x == "safety_items_expand_categories" else True
            response = self.client.get(reverse("safety"))
            self.assertRedirects(response, reverse("safety_categories"))

            # Case 2: safety_items_expand_categories = True
            mock_get_bool.side_effect = lambda x: True
            response = self.client.get(reverse("safety"))
            self.assertRedirects(response, reverse("safety_all_in_one"))

            # Case 3: Only safety issues enabled
            mock_get_bool.side_effect = lambda x: True if x == "safety_show_safety_issues" else False
            with patch(
                "NEMO.views.safety.navigation_url",
                side_effect=lambda url, desc: f"<li>{desc}</li>" if url == "safety_issues" else "",
            ):
                response = self.client.get(reverse("safety"))
                self.assertRedirects(response, reverse("safety_issues"))

            # Case 4: Only SDS enabled
            mock_get_bool.side_effect = lambda x: True if x == "safety_show_safety_data_sheets" else False
            with patch(
                "NEMO.views.safety.navigation_url",
                side_effect=lambda url, desc: f"<li>{desc}</li>" if url == "safety_data_sheets" else "",
            ):
                response = self.client.get(reverse("safety"))
                self.assertRedirects(response, reverse("safety_data_sheets"))

            # Case 5: Nothing enabled
            mock_get_bool.side_effect = lambda x: False
            with patch("NEMO.views.safety.navigation_url", return_value=""):
                # Based on the code, if everything is False, it redirects to safety_issues
                response = self.client.get(reverse("safety"))
                self.assertRedirects(response, reverse("safety_issues"))

    def test_safety_categories(self):
        self.login_as(self.user)
        cat = SafetyCategory.objects.create(name="Cat 1", display_order=1)
        item = SafetyItem.objects.create(name="Item 1", category=cat, display_order=1)

        response = self.client.get(reverse("safety_categories"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["category_id"], cat.id)

        response = self.client.get(reverse("safety_categories", kwargs={"category_id": cat.id}))
        self.assertEqual(response.status_code, 200)

        # Test with safety_item_id in GET
        response = self.client.get(reverse("safety_categories") + f"?safety_item_id={item.id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["category_id"], cat.id)

    def test_safety_all_in_one(self):
        self.login_as(self.user)
        cat = SafetyCategory.objects.create(name="Cat 1", display_order=1)
        SafetyItem.objects.create(name="Item 1", category=cat, display_order=1)
        SafetyItem.objects.create(name="General Item", display_order=2)

        response = self.client.get(reverse("safety_all_in_one"))
        self.assertEqual(response.status_code, 200)
        self.assertIn(cat, response.context["safety_categories"])
        self.assertEqual(response.context["safety_general"].count(), 1)

    def test_safety_item_redirect(self):
        self.login_as(self.user)
        item = SafetyItem.objects.create(name="Item 1", display_order=1)
        response = self.client.get(reverse("safety_item", kwargs={"safety_item_id": item.id}))
        self.assertIn(reverse("safety_categories"), response.url)
        self.assertIn(f"safety_item_id={item.id}", response.url)

    def test_safety_issues(self):
        self.login_as(self.user)
        issue = SafetyIssue.objects.create(concern="Broken", reporter=self.user)

        response = self.client.get(reverse("safety_issues"))
        self.assertEqual(response.status_code, 200)
        self.assertIn(issue, response.context["tickets"])

        # Test visible filter for non-staff
        issue.visible = False
        issue.save()
        response = self.client.get(reverse("safety_issues"))
        self.assertNotIn(issue, response.context["tickets"])

        # Staff can see it
        self.login_as(self.staff_user)
        response = self.client.get(reverse("safety_issues"))
        self.assertIn(issue, response.context["tickets"])

    def test_resolved_safety_issues(self):
        self.login_as(self.user)
        issue = SafetyIssue.objects.create(concern="Fixed", resolved=True, reporter=self.user)
        response = self.client.get(reverse("resolved_safety_issues"))
        self.assertEqual(response.status_code, 200)
        self.assertIn(issue, response.context["tickets"])

    def test_safety_data_sheets(self):
        self.login_as(self.user)
        h1 = ChemicalHazard.objects.create(name="Flammable", display_order=1)
        c1 = Chemical.objects.create(name="Acetone")
        c1.hazards.add(h1)
        c2 = Chemical.objects.create(name="Water")

        response = self.client.get(reverse("safety_data_sheets"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["chemicals"]), 2)

        # Test sorting
        response = self.client.get(reverse("safety_data_sheets") + "?o=name")
        self.assertEqual(response.context["chemicals"][0], c1)

        response = self.client.get(reverse("safety_data_sheets") + "?o=-name")
        self.assertEqual(response.context["chemicals"][0], c2)

        response = self.client.get(reverse("safety_data_sheets") + f"?o=hazard_{h1.id}")
        self.assertEqual(response.context["chemicals"][0], c1)

    def test_export_safety_data_sheets(self):
        self.login_as(self.staff_user)
        h1 = ChemicalHazard.objects.create(name="Flammable", display_order=1)
        c1 = Chemical.objects.create(name="Acetone")
        c1.hazards.add(h1)
        response = self.client.get(reverse("export_safety_data_sheets"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv")
        self.assertIn(b"Flammable", response.content)
        self.assertIn(b"Acetone", response.content)

    def test_create_safety_issue(self):
        self.login_as(self.user)
        response = self.client.get(reverse("create_safety_issue"))
        self.assertEqual(response.status_code, 200)

        response = self.client.post(reverse("create_safety_issue"), {"concern": "New Issue", "location": "Lab"})
        self.assertRedirects(response, reverse("safety_issues"))
        self.assertTrue(SafetyIssue.objects.filter(concern="New Issue", reporter=self.user).exists())

        # Anonymous
        response = self.client.post(
            reverse("create_safety_issue"), {"concern": "Anon Issue", "location": "Lab", "report_anonymously": True}
        )
        self.assertRedirects(response, reverse("safety_issues"))
        anon_issue = SafetyIssue.objects.get(concern="Anon Issue")
        self.assertIsNone(anon_issue.reporter)

    def test_update_safety_issue(self):
        self.login_as(self.staff_user)
        issue = SafetyIssue.objects.create(concern="Old", reporter=self.user)
        response = self.client.get(reverse("update_safety_issue", kwargs={"ticket_id": issue.id}))
        self.assertEqual(response.status_code, 200)

        response = self.client.post(
            reverse("update_safety_issue", kwargs={"ticket_id": issue.id}),
            {"update": "Updated progress", "resolved": False},
        )
        self.assertRedirects(response, reverse("safety_issues"))
        issue.refresh_from_db()
        self.assertIn("Updated progress", issue.progress)

        # Test resolution
        response = self.client.post(
            reverse("update_safety_issue", kwargs={"ticket_id": issue.id}),
            {"update": "Fixed now", "resolved": True},
        )
        self.assertRedirects(response, reverse("safety_issues"))
        issue.refresh_from_db()
        self.assertTrue(issue.resolved)
        self.assertEqual(issue.resolution, "Fixed now")

    def test_safety_items_search(self):
        self.login_as(self.user)
        SafetyItem.objects.create(name="SearchMe", display_order=1)
        response = self.client.get(
            reverse("safety_items_search") + "?q=SearchMe", HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"SearchMe", response.content)
