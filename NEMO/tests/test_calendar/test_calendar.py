from NEMO.models import User, Tool, Area
from NEMO.tests.test_utilities import login_as_user, test_response_is_failed_login, login_as_staff
from NEMO.views.customization import set_customization, get_customization
from django.test import TestCase
from django.urls import reverse


class CalendarTestCase(TestCase):
	tool:Tool = None
	owner:User = None
	area:Area = None

	def setUp(self):
		global tool, owner, area
		owner = User.objects.create(username='mctest', first_name='Testy', last_name='McTester')
		tool = Tool.objects.create(name='test_tool', primary_owner=owner, _category='Imaging')
		area = Area.objects.create(name='Cleanroom', welcome_message='')

	def test_calendar_urls(self):
		# if not logged in, it should send an error message
		response = self.client.get(reverse('calendar'), follow=True)
		test_response_is_failed_login(self, response)

		login_as_user(self.client)
		response = self.client.get(reverse('calendar'), follow=True)
		self.assertEqual(response.status_code, 200)

		response = self.client.get(reverse('calendar', kwargs={'item_type': 'tool', 'item_id': tool.id}), follow=True)
		self.assertEqual(response.status_code, 200)

	def test_self_login(self):
		login_as_user(self.client)
		set_customization("self_log_in", 'enabled')
		set_customization("self_log_out", 'enabled')
		set_customization("calendar_login_logout", 'enabled')
		response = self.client.get(reverse('calendar'), follow=True)
		self.assertEqual(response.status_code, 200)

		login_as_staff(self.client)
		response = self.client.get(reverse('calendar'), follow=True)
		self.assertEqual(response.status_code, 200)

	def test_event_feed(self):
		login_as_user(self.client)

		#Not sending any dates, should fail
		response = self.client.get(reverse('event_feed'), follow=True)
		self.assertEqual(response.status_code, 400)

		#Send random data to start , should fail
		response = self.client.get(reverse('event_feed'), data={'start':'jad', 'end':'2021-05-10'}, follow=True)
		self.assertEqual(response.status_code, 400)

		# Send random data to end , should fail
		response = self.client.get(reverse('event_feed'), data={'start':'2021-05-03', 'end':'jad'}, follow=True)
		self.assertEqual(response.status_code, 400)

		# No end date , should fail
		response = self.client.get(reverse('event_feed'), data={'start': '2021-05-03'}, follow=True)
		self.assertEqual(response.status_code, 400)

		# end < start, should fail
		response = self.client.get(reverse('event_feed'), data={'start': '2021-05-03', 'end': '2021-05-02'}, follow=True)
		self.assertEqual(response.status_code, 400)

		# Send start and end date, not event type, should fail
		response = self.client.get(reverse('event_feed'), data={'start': '2021-05-03', 'end': '2021-05-10'},follow=True)
		self.assertContains(response,'Invalid event type', status_code=400)

		# Send data, should pass
		response = self.client.get(reverse('event_feed'), data={'start': '2021-05-03', 'end': '2021-05-10', 'event_type':'reservations'},follow=True)
		self.assertEqual(response.status_code, 200)

		#test dates > 8 weeks, should fail
		response = self.client.get(reverse('event_feed'), data={'start': '2021-05-01', 'end': '2021-08-10', 'event_type':'reservations'},follow=True)
		self.assertEqual(response.status_code, 400)

		#test usage type (line 175)
	def test_reservation_event_feed(self):
		login_as_user(self.client)
		response = self.client.get(reverse('event_feed'),data={'item_type':'tool', 'item_id':tool.id,'start': '2021-05-03', 'end': '2021-05-10', 'event_type':'reservations'},follow=True)
		self.assertEqual(response.status_code, 200)
		response = self.client.get(reverse('event_feed'),data={'item_type': 'area', 'item_id': area.id, 'start': '2021-05-03','end': '2021-05-10', 'event_type': 'reservations'}, follow=True)
		self.assertEqual(response.status_code, 200)
		response = self.client.get(reverse('event_feed'),data={'personal_schedule':'True', 'start': '2021-05-03','end': '2021-05-10', 'event_type': 'reservations'}, follow=True)
		self.assertEqual(response.status_code, 200)

	#test usage event feed, should pass
	def test_usage_event_feed(self):
		login_as_user(self.client)
		facility_name = get_customization('facility_name')
		event_type = f"{facility_name.lower()} usage"
		response = self.client.get(reverse('event_feed'),data={'item_type': 'tool', 'item_id': tool.id, 'start': '2021-05-03','end': '2021-05-10', 'event_type': event_type}, follow=True)
		self.assertEqual(response.status_code, 200)
		response = self.client.get(reverse('event_feed'),data={'item_type': 'area', 'item_id': area.id, 'start': '2021-05-03','end': '2021-05-10', 'event_type': event_type}, follow=True)
		self.assertEqual(response.status_code, 200)
		response = self.client.get(reverse('event_feed'),data={'personal_schedule':'True', 'start': '2021-05-03','end': '2021-05-10', 'event_type': event_type}, follow=True)
		self.assertEqual(response.status_code, 200)

	#Test specific user feed, should pass
	def test_specific_user_feed(self):
		tester = login_as_staff(self.client)
		response = self.client.get(reverse('event_feed'),data={'user': tester.id, 'start': '2021-05-03','end': '2021-05-10', 'event_type': 'specific user'}, follow=True)
		self.assertEqual(response.status_code, 200)

	#Line 340 reservation_success find test already done


	#line 269 except user



