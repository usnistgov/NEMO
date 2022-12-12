import calendar
from datetime import datetime, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from NEMO.models import Area, Reservation, ReservationItemType, ScheduledOutage, Tool, User
from NEMO.tests.test_utilities import login_as_staff, login_as_user, test_response_is_landing_page
from NEMO.utilities import RecurrenceFrequency, localize


class OutageTestCase(TestCase):
	tool: Tool = None
	area: Area = None
	owner: User = None

	def setUp(self):
		global tool, area, owner
		owner = User.objects.create(username='mctest', first_name='Testy', last_name='McTester')
		tool = Tool.objects.create(name='test_tool', primary_owner=owner)
		area = Area.objects.create(name='Cleanroom', welcome_message='')

	@staticmethod
	def get_outage_data(title='', start: datetime = None, end: datetime = None, item_id: int = '', item_type: ReservationItemType = ReservationItemType.TOOL, outage: bool = False, frequency: RecurrenceFrequency = None, interval: int = '', until: datetime = None):
		if not start:
			start = datetime.now()
		if not end:
			end = start.replace(hour=start.hour + 1)
		data = {
			'title': title,
			'start': calendar.timegm(start.utctimetuple()),
			'end': calendar.timegm(end.utctimetuple()),
			'item_id': item_id if item_id else '',
			'item_type': item_type.value,
			'recurring_outage': 'on' if outage else '',
			'recurrence_frequency': frequency.value if frequency else '',
			'recurrence_interval': interval,
			'recurrence_until': localize(until).strftime('%m/%d/%Y') if until else ''
		}
		return data

	def test_outage_policy_problems(self):
		self.outage_policy_problems(tool.id, ReservationItemType.TOOL)
		self.outage_policy_problems(area.id, ReservationItemType.AREA)

	def outage_policy_problems(self, item_id: int, item_type: ReservationItemType):
		start = datetime.now()
		end = start - timedelta(hours=1)
		data = self.get_outage_data(start=start, end=end, item_id=item_id, item_type=item_type)

		# regular user should not be able to create outage
		login_as_user(self.client)
		response = self.client.get(reverse('create_outage'), {}, follow=True)
		test_response_is_landing_page(self, response)
		# back to staff mode
		login_as_staff(self.client)

		response = self.client.post(reverse('create_outage'), data, follow=True)
		self.assertEqual(response.status_code, 400)
		self.assertEqual(response.content.decode(), "The request parameters have an end time that precedes the start time.")

		# fix time
		end = (start + timedelta(hours=1))
		# Create a reservation and try to schedule an outage at the same time
		if item_type == ReservationItemType.TOOL:
			Reservation.objects.create(user=owner, creator=owner, tool=tool, start=start, end=end, short_notice=False)
		elif item_type == ReservationItemType.AREA:
			Reservation.objects.create(user=owner, creator=owner, area=area, start=start, end=end, short_notice=False)
		data = self.get_outage_data(start=start, end=end, item_id=item_id, item_type=item_type)
		response = self.client.post(reverse('create_outage'), data, follow=True)
		self.assertEqual(response.status_code, 400)
		self.assertEqual(response.content.decode(), "Your scheduled outage coincides with a reservation that already exists. Please choose a different time.")

		# try to schedule an outage that starts before but ends slightly after the reservation starts
		data = self.get_outage_data(start=start-timedelta(hours=1), end=end-timedelta(minutes=59), item_id=item_id, item_type=item_type)
		response = self.client.post(reverse('create_outage'), data, follow=True)
		self.assertEqual(response.status_code, 400)
		self.assertEqual(response.content.decode(), "Your scheduled outage coincides with a reservation that already exists. Please choose a different time.")

		# try to schedule an outage that starts slightly before the reservation ends
		data = self.get_outage_data(start=start + timedelta(minutes=59), end=end + timedelta(hours=1), item_id=item_id, item_type=item_type)
		response = self.client.post(reverse('create_outage'), data, follow=True)
		self.assertEqual(response.status_code, 400)
		self.assertEqual(response.content.decode(), "Your scheduled outage coincides with a reservation that already exists. Please choose a different time.")

		# no title
		start = start + timedelta(hours=2)
		end = end + timedelta(hours=2)
		data = self.get_outage_data(start=start, end=end, item_id=item_id, item_type=item_type)
		response = self.client.post(reverse('create_outage'), data, follow=True)
		self.assertEqual(response.status_code, 200) # response code valid but form is sent back. let's make sure the outage was indeed NOT created
		self.assertEqual(ScheduledOutage.objects.all().count(), 0)

	def test_create_outage(self):
		start = datetime.now()
		end = start + timedelta(hours=1)
		data = self.get_outage_data(title="Outage", start=start, end=end, item_id=tool.id)
		login_as_staff(self.client)
		response = self.client.post(reverse('create_outage'), data, follow=True)
		self.assertEqual(response.status_code, 200)
		self.assertEqual(ScheduledOutage.objects.all().count(), 1)
		self.assertTrue(ScheduledOutage.objects.get(title="Outage"))

	def test_create_area_outage(self):
		start = datetime.now()
		end = start + timedelta(hours=1)
		data = self.get_outage_data(title="Outage", start=start, end=end, item_id=area.id, item_type=ReservationItemType.AREA)
		login_as_staff(self.client)
		response = self.client.post(reverse('create_outage'), data, follow=True)
		self.assertEqual(response.status_code, 200)
		self.assertEqual(ScheduledOutage.objects.all().count(), 1)
		self.assertTrue(ScheduledOutage.objects.get(title="Outage"))

	def test_resize_outage(self):
		self.resize_outage(item_id=tool.id, item_type=ReservationItemType.TOOL)
		self.resize_outage(item_id=area.id, item_type=ReservationItemType.AREA)

	def resize_outage(self, item_id:int, item_type:ReservationItemType):
		# create outage
		start = datetime.now()
		end = start + timedelta(hours=1)
		data = self.get_outage_data(title="Outage", start=start, end=end,  item_id=item_id, item_type=item_type)
		login_as_staff(self.client)
		response = self.client.post(reverse('create_outage'), data, follow=True)
		self.assertEqual(response.status_code, 200)
		outage = ScheduledOutage.objects.get(title="Outage")
		self.assertTrue(outage.id)

		# regular user should not be able to resize outage
		login_as_user(self.client)
		response = self.client.get(reverse('resize_outage'), {}, follow=True)
		test_response_is_landing_page(self, response)
		self.assertTrue(ScheduledOutage.objects.get(pk=outage.id).id, outage.id)
		# back to staff mode
		login_as_staff(self.client)

		# test wrong delta
		response = self.client.post(reverse('resize_outage'), {'delta':'asd', 'id': outage.id}, follow=True)
		self.assertEqual(response.status_code, 400)
		self.assertEqual(response.content.decode(), "Invalid delta")

		# test no outage id
		response = self.client.post(reverse('resize_outage'), {'delta': 10}, follow=True)
		self.assertEqual(response.status_code, 404)
		self.assertEqual(response.content.decode(), "The outage that you wish to modify doesn't exist!")

		# test resize to less than original time
		response = self.client.post(reverse('resize_outage'), {'delta': -60, 'id': outage.id}, follow=True)
		self.assertEqual(response.status_code, 400)
		self.assertTrue('Outage start time' in response.content.decode())
		self.assertTrue('must be before the end time' in response.content.decode())

		# create a reservation and try to resize outage to overlap reservation
		start_reservation = end + timedelta(hours=1)
		end_reservation = start_reservation + timedelta(hours=1)

		if item_type == ReservationItemType.TOOL:
			Reservation.objects.create(user=owner, creator=owner, tool=tool, start=start_reservation, end=end_reservation, short_notice=False)
		elif item_type == ReservationItemType.AREA:
			Reservation.objects.create(user=owner, creator=owner, area=area, start=start_reservation, end=end_reservation, short_notice=False)
		response = self.client.post(reverse('resize_outage'), {'delta': 61, 'id': outage.id}, follow=True)
		self.assertEqual(response.status_code, 400)
		self.assertEqual(response.content.decode(), "Your scheduled outage coincides with a reservation that already exists. Please choose a different time.")

		# test reduce outage time by 10 min
		response = self.client.post(reverse('resize_outage'), {'delta': -10, 'id':outage.id}, follow=True)
		self.assertEqual(response.status_code, 200)
		self.assertEqual(ScheduledOutage.objects.get(pk=outage.id).end, outage.end - timedelta(minutes=10))

		# test increase outage time by 10 min
		outage = ScheduledOutage.objects.get(pk=outage.id)
		response = self.client.post(reverse('resize_outage'), {'delta': 10, 'id': outage.id}, follow=True)
		self.assertEqual(response.status_code, 200)
		self.assertEqual(ScheduledOutage.objects.get(pk=outage.id).end, outage.end + timedelta(minutes=10))

		outage.delete()

	def test_move_outage(self):
		self.move_outage(item_id=tool.id, item_type=ReservationItemType.TOOL)
		self.move_outage(item_id=area.id, item_type=ReservationItemType.AREA)

	def move_outage(self, item_id:int, item_type:ReservationItemType):
		# create outage
		start = datetime.now()
		end = start + timedelta(hours=1)
		data = self.get_outage_data(title="Outage", start=start, end=end, item_id=item_id, item_type=item_type)
		login_as_staff(self.client)
		response = self.client.post(reverse('create_outage'), data, follow=True)
		self.assertEqual(response.status_code, 200)
		outage = ScheduledOutage.objects.get(title="Outage")
		self.assertTrue(outage.id)

		# regular user should not be able to move outage
		login_as_user(self.client)
		response = self.client.get(reverse('move_outage'), {}, follow=True)
		test_response_is_landing_page(self, response)
		self.assertTrue(ScheduledOutage.objects.get(pk=outage.id).id, outage.id)
		# back to staff mode
		login_as_staff(self.client)

		# test wrong delta
		response = self.client.post(reverse('move_outage'), {'delta': 'asd', 'id': outage.id}, follow=True)
		self.assertEqual(response.status_code, 400)
		self.assertEqual(response.content.decode(), "Invalid delta")

		# test no outage id
		response = self.client.post(reverse('move_outage'), {'delta': 10}, follow=True)
		self.assertEqual(response.status_code, 404)
		self.assertEqual(response.content.decode(), "The outage that you wish to modify doesn't exist!")

		# create a reservation and try to move outage to overlap reservation
		start_reservation = end + timedelta(hours=1)
		end_reservation = start_reservation + timedelta(hours=1)
		if item_type == ReservationItemType.TOOL:
			Reservation.objects.create(user=owner, creator=owner, tool=tool, start=start_reservation, end=end_reservation, short_notice=False)
		elif item_type == ReservationItemType.AREA:
			Reservation.objects.create(user=owner, creator=owner, area=area, start=start_reservation, end=end_reservation, short_notice=False)

		response = self.client.post(reverse('move_outage'), {'delta': 61, 'id': outage.id}, follow=True)
		self.assertEqual(response.status_code, 400)
		self.assertEqual(response.content.decode(), "Your scheduled outage coincides with a reservation that already exists. Please choose a different time.")

		# test move outage 10 min earlier
		response = self.client.post(reverse('move_outage'), {'delta': -10, 'id': outage.id}, follow=True)
		self.assertEqual(response.status_code, 200)
		self.assertEqual(ScheduledOutage.objects.get(pk=outage.id).end, outage.end - timedelta(minutes=10))
		self.assertEqual(ScheduledOutage.objects.get(pk=outage.id).start, outage.start - timedelta(minutes=10))

		# test move outage 10 min later
		outage = ScheduledOutage.objects.get(pk=outage.id)
		response = self.client.post(reverse('move_outage'), {'delta': 10, 'id': outage.id}, follow=True)
		self.assertEqual(response.status_code, 200)
		self.assertEqual(ScheduledOutage.objects.get(pk=outage.id).end, outage.end + timedelta(minutes=10))
		self.assertEqual(ScheduledOutage.objects.get(pk=outage.id).start, outage.start + timedelta(minutes=10))
		outage.delete()

	def test_cancel_outage(self):
		self.cancel_outage(item_id=tool.id, item_type=ReservationItemType.TOOL)
		self.cancel_outage(item_id=area.id, item_type=ReservationItemType.AREA)

	def cancel_outage(self, item_id:int, item_type:ReservationItemType):
		# create outage
		start = datetime.now()
		end = start + timedelta(hours=1)
		data = self.get_outage_data(title="Outage", start=start, end=end, item_id=item_id, item_type=item_type)
		login_as_staff(self.client)
		response = self.client.post(reverse('create_outage'), data, follow=True)
		self.assertEqual(response.status_code, 200)
		outage = ScheduledOutage.objects.get(title="Outage")
		self.assertTrue(outage.id)

		# regular user should not be able to delete outage
		login_as_user(self.client)
		response = self.client.get(reverse('cancel_outage', kwargs={'outage_id': 999}), {}, follow=True)
		test_response_is_landing_page(self, response)
		self.assertTrue(ScheduledOutage.objects.get(pk=outage.id).id, outage.id)
		login_as_staff(self.client)

		# get should fail
		response = self.client.get(reverse('cancel_outage', kwargs={'outage_id': 999}), {}, follow=True)
		self.assertEqual(response.status_code, 405)

		# test wrong id
		response = self.client.post(reverse('cancel_outage', kwargs={'outage_id':999}), {}, follow=True)
		self.assertEqual(response.status_code, 404)

		response = self.client.post(reverse('cancel_outage', kwargs={'outage_id': outage.id}), {}, follow=True)
		self.assertEqual(response.status_code, 200)
		self.assertEqual(ScheduledOutage.objects.all().count(), 0)

	def test_outage_details(self):
		self.outage_details(item_id=tool.id, item_type=ReservationItemType.TOOL)
		self.outage_details(item_id=area.id, item_type=ReservationItemType.AREA)

	def outage_details(self, item_id:int, item_type:ReservationItemType):
		# create outage
		start = datetime.now()
		end = start + timedelta(hours=1)
		data = self.get_outage_data(title="Outage", start=start, end=end, item_id=item_id, item_type=item_type)
		login_as_staff(self.client)
		response = self.client.post(reverse('create_outage'), data, follow=True)
		self.assertEqual(response.status_code, 200)
		outage = ScheduledOutage.objects.get(title="Outage")
		self.assertTrue(outage.id)

		# anybody that is logged in can see outage details
		login_as_user(self.client)

		# post should fail
		response = self.client.post(reverse('outage_details', kwargs={'outage_id': 999}), {}, follow=True)
		self.assertEqual(response.status_code, 405)

		# test wrong id
		response = self.client.get(reverse('outage_details', kwargs={'outage_id':999}), {}, follow=True)
		self.assertEqual(response.status_code, 404)

		response = self.client.get(reverse('outage_details', kwargs={'outage_id': outage.id}), {}, follow=True)
		self.assertEqual(response.status_code, 200)

		outage.delete()

	def test_no_item_id_404(self):
		start = datetime.now()
		end = start + timedelta(hours=1)
		until = datetime.now() + timedelta(days=5)

		data = self.get_outage_data(start=start, end=end, outage=True, item_id=-1, frequency=RecurrenceFrequency.DAILY, interval=1, until=until)

		login_as_staff(self.client)
		response = self.client.post(reverse('create_outage'), data, follow=True)
		self.assertEqual(response.status_code, 404)

	def test_every_day_for_a_week(self):
		self.every_day_for_a_week(item_id=tool.id, item_type=ReservationItemType.TOOL)
		self.every_day_for_a_week(item_id=area.id, item_type=ReservationItemType.AREA)

	def every_day_for_a_week(self, item_id: int, item_type: ReservationItemType):
		start = datetime.now()
		end = start + timedelta(hours=1)
		until = datetime.now() + timedelta(days=6)

		data = self.get_outage_data(title='every day outage week', start=start, end=end, item_id=item_id, item_type=item_type, outage=True, frequency=RecurrenceFrequency.DAILY, interval=1, until=until)

		login_as_staff(self.client)
		response = self.client.post(reverse('create_outage'), data, follow=True)

		self.assertEqual(response.status_code, 200)
		outages = ScheduledOutage.objects.filter(title='every day outage week', tool=tool)
		self.assertEqual(len(outages), 7)

	def test_every_week_for_a_year(self):
		self.every_week_for_a_year(item_id=tool.id, item_type=ReservationItemType.TOOL)
		self.every_week_for_a_year(item_id=area.id, item_type=ReservationItemType.AREA)

	def every_week_for_a_year(self, item_id:int, item_type:ReservationItemType):
		start = (datetime.now() + timedelta(days=1)).replace(microsecond=0).replace(hour=7)
		end = start + timedelta(hours=1)
		until = datetime.now() + timedelta(days=365)

		data = self.get_outage_data(title='every day outage year', start=start, end=end, item_id=item_id, item_type=item_type, outage=True, frequency=RecurrenceFrequency.WEEKLY, interval=1, until=until)

		login_as_staff(self.client)
		response = self.client.post(reverse('create_outage'), data, follow=True)

		self.assertEqual(response.status_code, 200)
		outages = ScheduledOutage.objects.filter(title='every day outage year').filter(**{f'{item_type.value}__id':item_id})
		for outage in outages:
			good_start = outage.start.astimezone(timezone.get_current_timezone())
			good_end = outage.end.astimezone(timezone.get_current_timezone())
			self.assertEqual(good_start.weekday(), start.weekday())
			self.assertEqual(good_end.weekday(), end.weekday())
			self.assertEqual(good_start.time(), start.time())
			self.assertEqual(good_end.time(), end.time())

	def test_week_day(self):
		self.week_day(item_id=tool.id, item_type=ReservationItemType.TOOL)
		self.week_day(item_id=area.id, item_type=ReservationItemType.AREA)

	def week_day(self, item_id:int, item_type:ReservationItemType):
		start = datetime.now()
		end = start + timedelta(hours=1)
		until = datetime.now() + timedelta(weeks=9)

		data = self.get_outage_data(title='every week day outage', start=start, end=end, item_id=item_id, item_type=item_type, outage=True, frequency=RecurrenceFrequency.DAILY_WEEKDAYS, interval=1, until=until)

		login_as_staff(self.client)
		response = self.client.post(reverse('create_outage'), data, follow=True)

		self.assertEqual(response.status_code, 200)
		outages = ScheduledOutage.objects.filter(title='every week day outage', tool=tool)
		for outage in outages:
			# 0 is Monday, 5 & 6 are Saturday and Sunday
			self.assertLess(outage.start.astimezone(timezone.get_current_timezone()).weekday(), 5)

	def test_weekend(self):
		self.weekend(item_id=tool.id, item_type=ReservationItemType.TOOL)
		self.weekend(item_id=area.id, item_type=ReservationItemType.AREA)

	def weekend(self, item_id:int, item_type:ReservationItemType):
		start = datetime.now()
		end = start + timedelta(hours=1)
		until = datetime.now() + timedelta(weeks=9)

		data = self.get_outage_data(title='every weekend day outage', start=start, end=end, item_id=item_id, item_type=item_type, outage=True, frequency=RecurrenceFrequency.DAILY_WEEKENDS, interval=1, until=until)

		login_as_staff(self.client)
		response = self.client.post(reverse('create_outage'), data, follow=True)

		self.assertEqual(response.status_code, 200)
		outages = ScheduledOutage.objects.filter(title='every weekend day outage', tool=tool)
		for outage in outages:
			# 0 is Monday, 5 & 6 are Saturday and Sunday
			self.assertGreaterEqual(outage.start.astimezone(timezone.get_current_timezone()).weekday(), 5)
