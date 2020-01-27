from django.test import TestCase
from django.urls import reverse

from NEMO.models import User, Tool
from NEMO.tests.test_utilities import login_as_user, test_response_is_login_page


class CalendarTestCase(TestCase):
	tool = None
	owner = None

	def setUp(self):
		global tool, owner
		owner = User.objects.create(username='mctest', first_name='Testy', last_name='McTester')
		tool = Tool.objects.create(name='test_tool', primary_owner=owner, _category='Imaging')

	def test_calendar_urls(self):
		# if not logged in, it should redirect to login
		response = self.client.get(reverse('calendar'), follow=True)
		test_response_is_login_page(self, response)

		login_as_user(self.client)
		response = self.client.get(reverse('calendar'), follow=True)
		self.assertEquals(response.status_code, 200)

		response = self.client.get(reverse('calendar', kwargs={'tool_id': tool.id}), follow=True)
		self.assertEquals(response.status_code, 200)
