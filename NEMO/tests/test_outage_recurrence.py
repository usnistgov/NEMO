import calendar
from datetime import datetime, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from NEMO.models import ScheduledOutage, Tool, User
from NEMO.tests.test_utilities import login_as_staff
from NEMO.utilities import localize


class OutageRecurrenceTestCase(TestCase):
	tool = None

	def setUp(self):
		global tool
		owner = User.objects.create(username='mctest', first_name='Testy', last_name='McTester')
		tool = Tool.objects.create(name='test_tool', primary_owner=owner)

	@staticmethod
	def get_outage_data(title=None, start: datetime = None, end: datetime = None, tool_name: str = None, outage: bool = False, frequency: str = None, interval: int = None, until: datetime = None):
		if not start:
			start = datetime.now()
		if not end:
			end = start.replace(hour=start.hour + 1)
		data = {
			'title': title,
			'start': calendar.timegm(start.utctimetuple()),
			'end': calendar.timegm(end.utctimetuple()),
			'tool_name': tool_name,
			'recurring_outage': 'on' if outage else '',
			'recurrence_frequency': frequency,
			'recurrence_interval': interval,
			'recurrence_until': localize(until).strftime('%m/%d/%Y') if until else ''
		}
		return data

	def test_no_tool_name_404(self):
		start = datetime.now()
		end = start + timedelta(hours=1)
		until = datetime.now() + timedelta(days=5)

		data = self.get_outage_data(start=start, end=end, outage=True, frequency='DAILY', interval=1, until=until)

		login_as_staff(self.client)
		response = self.client.post(reverse('create_outage'), data, follow=True)
		self.assertEquals(response.status_code, 404)

	def test_every_day_for_a_week(self):
		start = datetime.now()
		end = start + timedelta(hours=1)
		until = datetime.now() + timedelta(days=6)

		data = self.get_outage_data(title='every day outage week', start=start, end=end, tool_name=tool.name, outage=True, frequency='DAILY', interval=1, until=until)

		login_as_staff(self.client)
		response = self.client.post(reverse('create_outage'), data, follow=True)

		self.assertEquals(response.status_code, 200)
		outages = ScheduledOutage.objects.filter(title='every day outage week', tool=tool)
		self.assertEqual(len(outages), 7)

	def test_every_week_for_a_year(self):
		start = datetime.now().replace(microsecond=0)
		end = start + timedelta(hours=1)
		until = datetime.now() + timedelta(days=365)

		data = self.get_outage_data(title='every day outage year', start=start, end=end, tool_name=tool.name, outage=True, frequency='WEEKLY', interval=1, until=until)

		login_as_staff(self.client)
		response = self.client.post(reverse('create_outage'), data, follow=True)

		self.assertEquals(response.status_code, 200)
		outages = ScheduledOutage.objects.filter(title='every day outage year', tool=tool)
		for outage in outages:
			good_start = outage.start.astimezone(timezone.get_current_timezone())
			good_end = outage.end.astimezone(timezone.get_current_timezone())
			self.assertEquals(good_start.weekday(), start.weekday())
			self.assertEquals(good_end.weekday(), end.weekday())
			self.assertEquals(good_start.time(), start.time())
			self.assertEquals(good_end.time(), end.time())

	def test_week_day(self):
		start = datetime.now()
		end = start + timedelta(hours=1)
		until = datetime.now() + timedelta(weeks=9)

		data = self.get_outage_data(title='every week day outage', start=start, end=end, tool_name=tool.name, outage=True, frequency='DAILY_WEEKDAYS', interval=1, until=until)

		login_as_staff(self.client)
		response = self.client.post(reverse('create_outage'), data, follow=True)

		self.assertEquals(response.status_code, 200)
		outages = ScheduledOutage.objects.filter(title='every week day outage', tool=tool)
		for outage in outages:
			# 0 is Monday, 5 & 6 are Saturday and Sunday
			self.assertLess(outage.start.astimezone(timezone.get_current_timezone()).weekday(), 5)

	def test_weekend(self):
		start = datetime.now()
		end = start + timedelta(hours=1)
		until = datetime.now() + timedelta(weeks=9)

		data = self.get_outage_data(title='every weekend day outage', start=start, end=end, tool_name=tool.name, outage=True, frequency='DAILY_WEEKENDS', interval=1, until=until)

		login_as_staff(self.client)
		response = self.client.post(reverse('create_outage'), data, follow=True)

		self.assertEquals(response.status_code, 200)
		outages = ScheduledOutage.objects.filter(title='every weekend day outage', tool=tool)
		for outage in outages:
			# 0 is Monday, 5 & 6 are Saturday and Sunday
			self.assertGreaterEqual(outage.start.astimezone(timezone.get_current_timezone()).weekday(), 5)
