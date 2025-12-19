from django.test import TestCase
from django.urls import reverse

from NEMO.models import Tool, User
from NEMO.tests.test_utilities import NEMOTestCaseMixin


class CalendarTestCase(NEMOTestCaseMixin, TestCase):
    tool = None
    owner = None

    def setUp(self):
        global tool, owner
        owner = User.objects.create(username="mctest", first_name="Testy", last_name="McTester")
        tool = Tool.objects.create(name="test_tool", primary_owner=owner, _category="Imaging")

    def test_calendar_urls(self):
        # if not logged in, it should send an error message
        response = self.client.get(reverse("calendar"), follow=True)
        self.assert_response_is_failed_login(response)

        self.login_as_user()
        response = self.client.get(reverse("calendar"), follow=True)
        self.assertEqual(response.status_code, 200)

        response = self.client.get(reverse("calendar", kwargs={"item_type": "tool", "item_id": tool.id}), follow=True)
        self.assertEqual(response.status_code, 200)
