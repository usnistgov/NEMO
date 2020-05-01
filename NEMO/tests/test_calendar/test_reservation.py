import calendar
from datetime import datetime, timedelta

from django.test import TestCase
from django.urls import reverse

from NEMO.models import User, Tool, ScheduledOutage, Reservation, Account, Project
from NEMO.tests.test_utilities import login_as_user, login_as


class ReservationTestCase(TestCase):
	tool: Tool = None
	owner: User = None
	consumer: User = None
	staff: User = None

	def setUp(self):
		global tool, consumer, staff
		owner = User.objects.create(username='mctest', first_name='Testy', last_name='McTester')
		tool = Tool.objects.create(name='test_tool', primary_owner=owner, _category='Imaging')
		account = Account.objects.create(name="account1")
		project = Project.objects.create(name="project1", account=account)
		staff = User.objects.create(username='staff', first_name='Staff', last_name='Member', is_staff=True)
		consumer = User.objects.create(username='jsmith', first_name='John', last_name='Smith', training_required=False)
		consumer.qualifications.add(tool)
		consumer.projects.add(project)
		consumer.save()

	@staticmethod
	def get_reservation_data(start: datetime, end:datetime, tool_param: Tool):
		return {
			'start':calendar.timegm(start.utctimetuple()),
			'end':calendar.timegm(end.utctimetuple()),
			'tool_name':tool_param.name,
		}

	def test_user_does_not_meet_conditions(self):
		user = User.objects.create(username='noproj', first_name='scott', last_name='NoProj')

		start = datetime.now() + timedelta(hours=1)
		end = start + timedelta(hours=1)
		data = self.get_reservation_data(start, end, tool)

		login_as(self.client, user)

		response = self.client.post(reverse('create_reservation'), data, follow=True)
		self.assertEqual(response.status_code, 200)
		self.assertTrue("You do not belong to any active projects. Thus, you may not create any reservations." in response.content.decode())
		self.assertTrue("You are blocked from making reservations for all tools in the NanoFab. Please complete the NanoFab rules tutorial in order to create new reservations." in response.content.decode())
		self.assertTrue("You are not qualified to use this tool. Creating, moving, and resizing reservations is forbidden." in response.content.decode())

		user.training_required = False
		user.save()
		login_as(self.client, user)
		response = self.client.post(reverse('create_reservation'), data, follow=True)
		self.assertEqual(response.status_code, 200)
		self.assertTrue("You are blocked from making reservations for all tools in the NanoFab. Please complete the NanoFab rules tutorial in order to create new reservations." not in response.content.decode())
		self.assertTrue("You do not belong to any active projects. Thus, you may not create any reservations." in response.content.decode())
		self.assertTrue("You are not qualified to use this tool. Creating, moving, and resizing reservations is forbidden." in response.content.decode())

		user.qualifications.add(tool)
		login_as(self.client, user)
		response = self.client.post(reverse('create_reservation'), data, follow=True)
		self.assertEqual(response.status_code, 200)
		self.assertTrue("You are not qualified to use this tool. Creating, moving, and resizing reservations is forbidden." not in response.content.decode())
		self.assertTrue("You do not belong to any active projects. Thus, you may not create any reservations." in response.content.decode())

	def test_reservation_policy_problems(self):
		# start tomorrow 2am
		dt_now = datetime.now()
		base_start = datetime(dt_now.year, dt_now.month, dt_now.day) + timedelta(days=1, hours=2)
		end = base_start - timedelta(hours=1)
		data = self.get_reservation_data(base_start, end, tool)

		login_as(self.client, consumer)

		response = self.client.post(reverse('create_reservation'), data, follow=True)
		self.assertEqual(response.status_code, 400)
		self.assertEqual(response.content.decode(), "The request parameters have an end time that precedes the start time.")

		# fix time
		end = (base_start + timedelta(hours=1))
		# Create a outage and try to schedule a reservation at the same time
		outage = ScheduledOutage.objects.create(title="Outage", tool=tool, start=base_start, end=end, creator=staff)
		data = self.get_reservation_data(base_start, end, tool)
		response = self.client.post(reverse('create_reservation'), data, follow=True)
		self.assertEqual(response.status_code, 200)
		self.assertTrue("Your reservation coincides with a scheduled outage. Please choose a different time." in response.content.decode())

		# try to schedule a reservation that starts before but ends slightly after the outage starts
		data = self.get_reservation_data(base_start - timedelta(hours=1), end - timedelta(minutes=59), tool)
		response = self.client.post(reverse('create_reservation'), data, follow=True)
		self.assertEqual(response.status_code, 200)
		self.assertTrue("Your reservation coincides with a scheduled outage. Please choose a different time." in response.content.decode())

		# try to schedule a reservation that starts slightly before the outage ends
		data = self.get_reservation_data(base_start + timedelta(minutes=59), end + timedelta(hours=1), tool)
		response = self.client.post(reverse('create_reservation'), data, follow=True)
		self.assertEqual(response.status_code, 200)
		self.assertTrue("Your reservation coincides with a scheduled outage. Please choose a different time." in response.content.decode())

		outage.delete()

		# try to schedule a reservation in the past
		data = self.get_reservation_data(base_start - timedelta(days=1), end - timedelta(days=1), tool)
		response = self.client.post(reverse('create_reservation'), data, follow=True)
		self.assertEqual(response.status_code, 200)
		self.assertTrue("start time" in response.content.decode() and  "is earlier than the current time" in response.content.decode())

		# check tool horizon (days in advance to reserve tool)
		tool.reservation_horizon = 2
		tool.save()
		start = base_start + timedelta(days=3)
		end = start + timedelta(hours=1)
		data = self.get_reservation_data(start, end, tool)

		login_as(self.client, consumer)
		response = self.client.post(reverse('create_reservation'), data, follow=True)
		self.assertEqual(response.status_code, 200)
		self.assertTrue("You may not create reservations further than 2 days from now for this tool." in response.content.decode())
		self.assertEqual(Reservation.objects.filter(tool=tool).count(), 0)

		# minimum & maximum duration
		tool.minimum_usage_block_time = 90
		tool.maximum_usage_block_time = 30
		tool.save()
		start = base_start + timedelta(hours=1)
		end = start + timedelta(hours=1)
		data = self.get_reservation_data(start, end, tool)

		login_as(self.client, consumer)
		response = self.client.post(reverse('create_reservation'), data, follow=True)
		self.assertEqual(response.status_code, 200)
		self.assertTrue("Your reservation has a duration of 60 minutes. This tool requires a minimum reservation duration of 90 minutes." in response.content.decode())
		self.assertTrue("Your reservation has a duration of 60 minutes. Reservations for this tool may not exceed 30 minutes." in response.content.decode())
		self.assertEqual(Reservation.objects.filter(tool=tool).count(), 0)

		# max reservations per day
		first_of_the_day = Reservation.objects.create(tool=tool, start=start, end=end, creator=consumer, user=consumer, short_notice=False)
		tool.maximum_reservations_per_day = 1
		tool.minimum_usage_block_time = None
		tool._maximum_usage_block_time = None
		tool.save()
		data = self.get_reservation_data(start + timedelta(hours=2), end + timedelta(hours=2), tool)
		response = self.client.post(reverse('create_reservation'), data, follow=True)
		self.assertEqual(response.status_code, 200)
		self.assertTrue("You may only have 1 reservations for this tool per day. Missed reservations are included when counting the number of reservations per day" in response.content.decode())

		# even if the first one was missed, still counts towards the limit
		first_of_the_day.missed = True
		first_of_the_day.save()
		data = self.get_reservation_data(start + timedelta(hours=2), end + timedelta(hours=2), tool)
		response = self.client.post(reverse('create_reservation'), data, follow=True)
		self.assertEqual(response.status_code, 200)
		self.assertTrue("You may only have 1 reservations for this tool per day. Missed reservations are included when counting the number of reservations per day" in response.content.decode())

		# test minimum time between reservations
		first_of_the_day.missed = False
		first_of_the_day.save()

		tool.maximum_reservations_per_day = None
		tool.minimum_time_between_reservations = 120
		tool.save()
		data = self.get_reservation_data(start + timedelta(minutes=90), end + timedelta(minutes=90), tool)
		response = self.client.post(reverse('create_reservation'), data, follow=True)
		self.assertEqual(response.status_code, 200)
		self.assertTrue("Separate reservations for this tool that belong to you must be at least 120 minutes apart from each other. The proposed reservation ends too close to another reservation." in response.content.decode())

		data = self.get_reservation_data(start + timedelta(minutes=30), start + timedelta(minutes=90), tool)
		response = self.client.post(reverse('create_reservation'), data, follow=True)
		self.assertEqual(response.status_code, 200)
		self.assertTrue("Separate reservations for this tool that belong to you must be at least 120 minutes apart from each other. The proposed reservation begins too close to another reservation." in response.content.decode())
		self.assertTrue("Separate reservations for this tool that belong to you must be at least 120 minutes apart from each other. The proposed reservation ends too close to another reservation." in response.content.decode())

		tool.maximum_future_reservation_time = 90
		tool.minimum_time_between_reservations = None
		tool.save()
		data = self.get_reservation_data(start + timedelta(minutes=90), end + timedelta(minutes=90), tool)
		response = self.client.post(reverse('create_reservation'), data, follow=True)
		self.assertEqual(response.status_code, 200)
		self.assertTrue("You may only reserve up to 90 minutes of time on this tool, starting from the current time onward." in response.content.decode())

		first_of_the_day.delete()

	def test_create_reservation(self):
		start = datetime.now() + timedelta(hours=1)
		end = start + timedelta(hours=1)
		data = self.get_reservation_data(start, end, tool)

		login_as(self.client, consumer)
		response = self.client.post(reverse('create_reservation'), data, follow=True)
		self.assertEqual(response.status_code, 200)
		self.assertEqual(Reservation.objects.all().count(), 1)
		self.assertTrue(Reservation.objects.get(tool=tool))

	def test_create_reservation_multi_projects(self):
		start = datetime.now() + timedelta(hours=1)
		end = start + timedelta(hours=1)
		data = self.get_reservation_data(start, end, tool)

		login_as(self.client, consumer)

		second_project = Project.objects.create(name="project2", account=Account.objects.get(name='account1'))
		consumer.projects.add(second_project)

		# test creating reservation on a project the user is not associated with (trying to bill another project)
		not_my_project = Project.objects.create(name="not my project", account=Account.objects.get(name="account1"))
		data['project_id'] = not_my_project.id
		response = self.client.post(reverse('create_reservation'), data, follow=True)
		self.assertEqual(response.status_code, 200)
		self.assertEqual(Reservation.objects.all().count(), 0)
		self.assertTrue("Associate your reservation with a project." in response.content.decode())

		# test not sending project id
		data['project_id'] = ''
		response = self.client.post(reverse('create_reservation'), data, follow=True)
		self.assertEqual(response.status_code, 200)
		self.assertEqual(Reservation.objects.all().count(), 0)
		self.assertTrue("Associate your reservation with a project." in response.content.decode())

		data['project_id'] = second_project.id
		response = self.client.post(reverse('create_reservation'), data, follow=True)
		self.assertEqual(response.status_code, 200)
		self.assertEqual(Reservation.objects.all().count(), 1)
		self.assertTrue(Reservation.objects.get(tool=tool))

	def test_create_reservation_for_somebody_else(self):
		start = datetime.now() + timedelta(hours=1)
		end = start + timedelta(hours=1)
		data = self.get_reservation_data(start, end, tool)
		data['impersonate'] = consumer.id

		login_as(self.client, staff)
		response = self.client.post(reverse('create_reservation'), data, follow=True)
		self.assertEqual(response.status_code, 200)
		self.assertEqual(Reservation.objects.all().count(), 1)
		self.assertTrue(Reservation.objects.get(tool=tool))
		self.assertEqual(Reservation.objects.get(tool=tool).user, consumer)
		self.assertEqual(Reservation.objects.get(tool=tool).creator, staff)

	def test_resize_reservation(self):
		# create reservation
		start = datetime.now() + timedelta(hours=1)
		end = start + timedelta(hours=1)
		data = self.get_reservation_data(start, end, tool)

		login_as(self.client, consumer)
		response = self.client.post(reverse('create_reservation'), data, follow=True)
		self.assertEqual(response.status_code, 200)
		reservation = Reservation.objects.get(tool=tool)
		self.assertTrue(reservation.id)

		# test wrong delta
		response = self.client.post(reverse('resize_reservation'), {'delta': 'asd', 'id': reservation.id}, follow=True)
		self.assertEqual(response.status_code, 400)
		self.assertEqual(response.content.decode(), "Invalid delta")

		# test no reservation id
		response = self.client.post(reverse('resize_reservation'), {'delta': 10}, follow=True)
		self.assertEqual(response.status_code, 404)
		self.assertEqual(response.content.decode(), "The reservation that you wish to modify doesn't exist!")

		# test resize to less than original time
		response = self.client.post(reverse('resize_reservation'), {'delta': -60, 'id': reservation.id}, follow=True)
		self.assertEqual(response.status_code, 400)
		self.assertTrue('Reservation start time' in response.content.decode())
		self.assertTrue('must be before the end time' in response.content.decode())

		# test resize to end before now
		old_resa = Reservation.objects.create(tool=tool, start=datetime.now() - timedelta(hours=1), end=datetime.now() + timedelta(hours=1), creator=consumer, user=consumer, short_notice=False)
		response = self.client.post(reverse('resize_reservation'), {'delta': -65, 'id': old_resa.id}, follow=True)
		self.assertEqual(response.status_code, 400)
		self.assertTrue('Reservation start time' in response.content.decode())
		self.assertTrue('is earlier than the current time' in response.content.decode())
		old_resa.delete()

		# create a outage and try to resize reservation to overlap outage
		start_reservation = end + timedelta(hours=1)
		end_reservation = start_reservation + timedelta(hours=1)
		ScheduledOutage.objects.create(tool=tool, start=start_reservation, end=end_reservation, creator=staff)
		response = self.client.post(reverse('resize_reservation'), {'delta': 61, 'id': reservation.id}, follow=True)
		self.assertEquals(response.status_code, 400)
		self.assertEquals(response.content.decode(), "Your reservation coincides with a scheduled outage. Please choose a different time.")

		# test reduce reservation time by 10 min
		response = self.client.post(reverse('resize_reservation'), {'delta': -10, 'id': reservation.id}, follow=True)
		self.assertEquals(response.status_code, 200)
		old_reservation = Reservation.objects.get(pk=reservation.id)
		self.assertTrue(old_reservation.cancelled)
		self.assertEquals(old_reservation.cancelled_by, consumer)
		self.assertEquals(Reservation.objects.filter(tool=tool, cancelled=False).count(), 1)
		new_reservation = list(Reservation.objects.filter(tool=tool, cancelled=False))[0]
		self.assertEquals(new_reservation.end, old_reservation.end - timedelta(minutes=10))

		# test resize cancelled reservation
		reservation = Reservation.objects.get(pk=reservation.id)
		response = self.client.post(reverse('resize_reservation'), {'delta': 10, 'id': reservation.id}, follow=True)
		self.assertEquals(response.status_code, 400)
		self.assertTrue("This reservation has already been cancelled" in response.content.decode())

		# test increase reservation time by 10 min
		response = self.client.post(reverse('resize_reservation'), {'delta': 10, 'id': new_reservation.id}, follow=True)
		self.assertEquals(response.status_code, 200)
		old_reservation = Reservation.objects.get(pk=new_reservation.id)
		self.assertTrue(old_reservation.cancelled)
		self.assertEquals(old_reservation.cancelled_by, consumer)
		self.assertEquals(Reservation.objects.filter(tool=tool, cancelled=False).count(), 1)
		new_reservation = list(Reservation.objects.filter(tool=tool, cancelled=False))[0]
		self.assertEquals(new_reservation.end, old_reservation.end + timedelta(minutes=10))

	def test_move_reservation(self):
		# create reservation
		start = datetime.now() + timedelta(hours=1)
		end = start + timedelta(hours=1)
		data = self.get_reservation_data(start, end, tool)

		login_as(self.client, consumer)
		response = self.client.post(reverse('create_reservation'), data, follow=True)
		self.assertEquals(response.status_code, 200)
		reservation = Reservation.objects.get(tool=tool)
		self.assertTrue(reservation.id)

		# test wrong delta
		response = self.client.post(reverse('move_reservation'), {'delta': 'asd', 'id': reservation.id}, follow=True)
		self.assertEquals(response.status_code, 400)
		self.assertEquals(response.content.decode(), "Invalid delta")

		# test no reservation id
		response = self.client.post(reverse('move_reservation'), {'delta': 10}, follow=True)
		self.assertEquals(response.status_code, 404)
		self.assertEquals(response.content.decode(), "The reservation that you wish to modify doesn't exist!")

		# create a outage and try to move reservation to overlap reservation
		start_reservation = end + timedelta(hours=1)
		end_reservation = start_reservation + timedelta(hours=1)
		ScheduledOutage.objects.create(tool=tool, start=start_reservation, end=end_reservation, creator=staff)
		response = self.client.post(reverse('move_reservation'), {'delta': 61, 'id': reservation.id}, follow=True)
		self.assertEquals(response.status_code, 400)
		self.assertEquals(response.content.decode(), "Your reservation coincides with a scheduled outage. Please choose a different time.")

		# test move reservation 10 min earlier
		response = self.client.post(reverse('move_reservation'), {'delta': -10, 'id': reservation.id}, follow=True)
		self.assertEquals(response.status_code, 200)
		old_reservation = Reservation.objects.get(pk=reservation.id)
		self.assertTrue(old_reservation.cancelled)
		self.assertEquals(old_reservation.cancelled_by, consumer)
		self.assertEquals(Reservation.objects.filter(tool=tool, cancelled=False).count(), 1)
		new_reservation = list(Reservation.objects.filter(tool=tool, cancelled=False))[0]
		self.assertEquals(new_reservation.end, old_reservation.end - timedelta(minutes=10))
		self.assertEquals(new_reservation.start, old_reservation.start - timedelta(minutes=10))

		# test move cancelled reservation
		reservation = Reservation.objects.get(pk=reservation.id)
		response = self.client.post(reverse('move_reservation'), {'delta': 10, 'id': reservation.id}, follow=True)
		self.assertEquals(response.status_code, 400)
		self.assertTrue("This reservation has already been cancelled" in response.content.decode())

		# test move new reservation 10 min later
		response = self.client.post(reverse('move_reservation'), {'delta': 10, 'id': new_reservation.id}, follow=True)
		self.assertEquals(response.status_code, 200)
		old_reservation = Reservation.objects.get(pk=new_reservation.id)
		self.assertTrue(old_reservation.cancelled)
		self.assertEquals(old_reservation.cancelled_by, consumer)
		self.assertEquals(Reservation.objects.filter(tool=tool, cancelled=False).count(), 1)
		new_reservation = list(Reservation.objects.filter(tool=tool, cancelled=False))[0]
		self.assertEquals(new_reservation.end, old_reservation.end + timedelta(minutes=10))
		self.assertEquals(new_reservation.start, old_reservation.start + timedelta(minutes=10))

	def test_cancel_reservation(self):
		# create reservation
		start = datetime.now() + timedelta(hours=1)
		end = start + timedelta(hours=1)
		data = self.get_reservation_data(start, end, tool)

		login_as(self.client, consumer)
		response = self.client.post(reverse('create_reservation'), data, follow=True)
		self.assertEquals(response.status_code, 200)
		reservation = Reservation.objects.get(tool=tool)
		self.assertTrue(reservation.id)

		# get should fail
		response = self.client.get(reverse('cancel_reservation', kwargs={'reservation_id': 999}), {}, follow=True)
		self.assertEquals(response.status_code, 405)

		# test wrong id
		response = self.client.post(reverse('cancel_reservation', kwargs={'reservation_id': 999}), {}, follow=True)
		self.assertEquals(response.status_code, 404)

		# test non staff user trying to cancel reservation
		login_as_user(self.client)
		response = self.client.post(reverse('cancel_reservation', kwargs={'reservation_id': reservation.id}), {}, follow=True)
		self.assertEquals(response.status_code, 400)
		self.assertEquals("You must provide a reason when cancelling someone else's reservation.", response.content.decode())

		response = self.client.post(reverse('cancel_reservation', kwargs={'reservation_id': reservation.id}), {'reason':'reason'}, follow=True)
		self.assertEquals(response.status_code, 400)
		self.assertEquals("You may not cancel reservations that you do not own.", response.content.decode())

		login_as(self.client, consumer)

		# test cancel missed reservation
		missed_resa = Reservation.objects.create(tool=tool, start=start+timedelta(days=1), end=end+timedelta(days=1), user=consumer, creator=consumer, missed=True, short_notice=False)
		response = self.client.post(reverse('cancel_reservation', kwargs={'reservation_id': missed_resa.id}), {}, follow=True)
		self.assertEquals(response.status_code, 400)
		self.assertEquals(response.content.decode(), "This reservation was missed and cannot be modified.")

		# test cancel already ended reservation
		already_ended_resa = Reservation.objects.create(tool=tool, start=start - timedelta(days=1), end=end - timedelta(days=1), user=consumer, creator=consumer, missed=True, short_notice=False)
		response = self.client.post(reverse('cancel_reservation', kwargs={'reservation_id': already_ended_resa.id}), {}, follow=True)
		self.assertEquals(response.status_code, 400)
		self.assertEquals(response.content.decode(), "You may not cancel reservations that have already ended.")

		# cancel reservation
		response = self.client.post(reverse('cancel_reservation', kwargs={'reservation_id': reservation.id}), {}, follow=True)
		self.assertEquals(response.status_code, 200)
		self.assertTrue(Reservation.objects.get(pk=reservation.id).cancelled)
		self.assertEquals(Reservation.objects.get(pk=reservation.id).cancelled_by, consumer)

		# test cancel already cancelled reservation
		response = self.client.post(reverse('cancel_reservation', kwargs={'reservation_id': reservation.id}), {}, follow=True)
		self.assertEquals(response.status_code, 400)
		self.assertTrue("This reservation has already been cancelled by " in response.content.decode())

		# test staff cancelling somebody else's reservation
		other_resa = Reservation.objects.create(tool=tool, start=start - timedelta(days=1),	end=end - timedelta(days=1), user=consumer, creator=consumer, short_notice=False)
		login_as(self.client, staff)
		response = self.client.post(reverse('cancel_reservation', kwargs={'reservation_id': other_resa.id}), {}, follow=True)
		self.assertEquals(response.status_code, 400)
		self.assertEquals("You must provide a reason when cancelling someone else's reservation.", response.content.decode())

		response = self.client.post(reverse('cancel_reservation', kwargs={'reservation_id': other_resa.id}), {'reason': 'reason'}, follow=True)
		self.assertEquals(response.status_code, 200)
		self.assertTrue(Reservation.objects.get(pk=other_resa.id).cancelled)
		self.assertEquals(Reservation.objects.get(pk=other_resa.id).cancelled_by, staff)

	def test_reservation_details(self):
		# create reservation
		start = datetime.now() + timedelta(hours=1)
		end = start + timedelta(hours=1)
		data = self.get_reservation_data(start, end, tool)

		login_as(self.client, consumer)
		response = self.client.post(reverse('create_reservation'), data, follow=True)
		self.assertEquals(response.status_code, 200)
		reservation = Reservation.objects.get(tool=tool)
		self.assertTrue(reservation.id)

		# anybody that is logged in can see reservation details
		login_as_user(self.client)

		# post should fail
		response = self.client.post(reverse('reservation_details', kwargs={'reservation_id': 999}), {}, follow=True)
		self.assertEquals(response.status_code, 405)

		# test wrong id
		response = self.client.get(reverse('reservation_details', kwargs={'reservation_id': 999}), {}, follow=True)
		self.assertEquals(response.status_code, 404)

		response = self.client.get(reverse('reservation_details', kwargs={'reservation_id': reservation.id}), {}, follow=True)
		self.assertEquals(response.status_code, 200)

	def test_reservation_with_tool_configuration(self):
		# TODO: create those tests
		self.assertTrue(True)

	def test_reservation_policy_off(self):
		# TODO: create those tests
		self.assertTrue(True)
