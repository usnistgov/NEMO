from django.test import TestCase

from NEMO.models import Tool, User
from NEMO.templatetags.custom_tags_and_filters import is_staff_on_tool


class TestStaffOnToolFilter(TestCase):
    def setUp(self):
        self.user = User.objects.create(username="test_user", is_superuser=False, is_staff=False)
        self.staff_user = User.objects.create(username="staff_user", is_staff=True)
        self.tool = Tool.objects.create(name="Tool 1")

    def test_staff_on_tool_with_none_user(self):
        result = is_staff_on_tool(None, self.tool)
        self.assertFalse(result)

    def test_staff_on_tool_with_staff_user(self):
        result = is_staff_on_tool(self.staff_user, self.tool)
        self.assertTrue(result)

    def test_staff_on_tool_with_none_tool(self):
        result = is_staff_on_tool(self.user, None)
        self.assertFalse(result)
