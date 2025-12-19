from django.test import TestCase

from NEMO.tests.test_utilities import create_user_and_project, NEMOTestCaseMixin


class TestAutocompleteViewWithFixedPermissions(NEMOTestCaseMixin, TestCase):
    def setUp(self):
        self.user, project = create_user_and_project()

    def test_view_with_add_permission(self):
        self.login_as_user_with_permissions(["add_staffcharge"])
        response = self.client.get("/admin/autocomplete/?app_label=NEMO&model_name=staffcharge&field_name=customer")
        self.assertEqual(response.status_code, 200)

    def test_view_with_change_permission(self):
        self.login_as_user_with_permissions(["change_staffcharge"])
        response = self.client.get("/admin/autocomplete/?app_label=NEMO&model_name=staffcharge&field_name=customer")
        self.assertEqual(response.status_code, 200)

    def test_view_without_permissions(self):
        self.login_as_user_with_permissions(["view_staffcharge"])
        response = self.client.get("/admin/autocomplete/?app_label=NEMO&model_name=staffcharge&field_name=customer")
        self.assertEqual(
            response.status_code, 403, msg="View only permission should not allow displaying autocomplete results"
        )
