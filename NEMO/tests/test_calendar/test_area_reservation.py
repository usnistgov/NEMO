import calendar
from datetime import datetime, timedelta

from django.test import TestCase
from django.urls import reverse

from NEMO.models import User, ScheduledOutage, Reservation, Account, Project, Area, PhysicalAccessLevel, \
	AreaAccessRecord
from NEMO.tests.test_utilities import login_as_user, login_as


class AreaReservationTestCase(TestCase):
	area: Area = None
	area_access_level = None
	owner: User = None
	consumer: User = None
	staff: User = None
	project: Project = None

	def setUp(self):
		global area, area_access_level, consumer, staff, project
		area = Area.objects.create(name='test_area', requires_reservation=True, category='Imaging')
		area_access_level = PhysicalAccessLevel.objects.create(name='area access level', area=area, schedule=PhysicalAccessLevel.Schedule.ALWAYS)
		account = Account.objects.create(name="account1")
		project = Project.objects.create(name="project1", account=account)
		staff = User.objects.create(username='staff', first_name='Staff', last_name='Member', is_staff=True)
		consumer = User.objects.create(username='jsmith', first_name='John', last_name='Smith', training_required=False)
		consumer.physical_access_levels.add(area_access_level)
		consumer.projects.add(project)
		consumer.save()

	@staticmethod
	def get_reservation_data(start: datetime, end:datetime, area_param: Area):
		return {
			'start':calendar.timegm(start.utctimetuple()),
			'end':calendar.timegm(end.utctimetuple()),
			'item_id':area_param.id,
			'item_type':'area',
		}

	def test_user_does_not_meet_conditions(self):
		user = User.objects.create(username='noproj', first_name='scott', last_name='NoProj')

		start = datetime.now() + timedelta(hours=1)
		end = start + timedelta(hours=1)
		data = self.get_reservation_data(start, end, area)

		login_as(self.client, user)

		response = self.client.post(reverse('create_reservation'), data, follow=True)
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "You do not belong to any active projects. Thus, you may not create any reservations.")
		self.assertContains(response, "You are blocked from making reservations in the NanoFab. Please complete the NanoFab rules tutorial in order to create new reservations.")
		self.assertContains(response, "You are not authorized to access this area at this time. Creating, moving, and resizing reservations is forbidden.")

		user.training_required = False
		user.save()
		login_as(self.client, user)
		response = self.client.post(reverse('create_reservation'), data, follow=True)
		self.assertEqual(response.status_code, 200)
		self.assertNotContains(response, "You are blocked from making reservations in the NanoFab. Please complete the NanoFab rules tutorial in order to create new reservations.")
		self.assertContains(response, "You do not belong to any active projects. Thus, you may not create any reservations.")
		self.assertContains(response, "You are not authorized to access this area at this time. Creating, moving, and resizing reservations is forbidden.")

		user.physical_access_levels.add(area_access_level)
		login_as(self.client, user)
		response = self.client.post(reverse('create_reservation'), data, follow=True)
		self.assertEqual(response.status_code, 200)
		self.assertNotContains(response, "You are not qualified to use this area. Creating, moving, and resizing reservations is forbidden.")
		self.assertContains(response, "You do not belong to any active projects. Thus, you may not create any reservations.")

	def test_reservation_policy_problems(self):
		# start tomorrow 2am
		dt_now = datetime.now()
		base_start = datetime(dt_now.year, dt_now.month, dt_now.day) + timedelta(days=1, hours=2)
		end = base_start - timedelta(hours=1)
		data = self.get_reservation_data(base_start, end, area)

		login_as(self.client, consumer)

		response = self.client.post(reverse('create_reservation'), data, follow=True)
		self.assertEqual(response.status_code, 400)
		self.assertEqual(response.content.decode(), "The request parameters have an end time that precedes the start time.")

		# fix time
		end = (base_start + timedelta(hours=1))
		# Create a outage and try to schedule a reservation at the same time
		outage = ScheduledOutage.objects.create(title="Outage", area=area, start=base_start, end=end, creator=staff)
		data = self.get_reservation_data(base_start, end, area)
		response = self.client.post(reverse('create_reservation'), data, follow=True)
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Your reservation coincides with a scheduled outage. Please choose a different time.")

		# try to schedule a reservation that starts before but ends slightly after the outage starts
		data = self.get_reservation_data(base_start - timedelta(hours=1), end - timedelta(minutes=59), area)
		response = self.client.post(reverse('create_reservation'), data, follow=True)
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Your reservation coincides with a scheduled outage. Please choose a different time.")

		# try to schedule a reservation that starts slightly before the outage ends
		data = self.get_reservation_data(base_start + timedelta(minutes=59), end + timedelta(hours=1), area)
		response = self.client.post(reverse('create_reservation'), data, follow=True)
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Your reservation coincides with a scheduled outage. Please choose a different time.")

		outage.delete()

		# try to schedule a reservation in the past
		data = self.get_reservation_data(base_start - timedelta(days=1, hours=2), end - timedelta(days=1), area)
		response = self.client.post(reverse('create_reservation'), data, follow=True)
		self.assertEqual(response.status_code, 200)
		self.assertTrue("start time" in response.content.decode() and  "is earlier than the current time" in response.content.decode())

		# check area horizon (days in advance to reserve area)
		area.reservation_horizon = 2
		area.save()
		start = base_start + timedelta(days=3)
		end = start + timedelta(hours=1)
		data = self.get_reservation_data(start, end, area)

		login_as(self.client, consumer)
		response = self.client.post(reverse('create_reservation'), data, follow=True)
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "You may not create reservations further than 2 days from now for this area.")
		self.assertEqual(Reservation.objects.filter(area=area).count(), 0)

		# minimum & maximum duration
		area.minimum_usage_block_time = 90
		area.maximum_usage_block_time = 30
		area.save()
		start = base_start + timedelta(hours=1)
		end = start + timedelta(hours=1)
		data = self.get_reservation_data(start, end, area)

		login_as(self.client, consumer)
		response = self.client.post(reverse('create_reservation'), data, follow=True)
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Your reservation has a duration of 60 minutes. This area requires a minimum reservation duration of 90 minutes.")
		self.assertContains(response, "Your reservation has a duration of 60 minutes. Reservations for this area may not exceed 30 minutes.")
		self.assertEqual(Reservation.objects.filter(area=area).count(), 0)

		# max reservations per day
		first_of_the_day = Reservation.objects.create(area=area, start=start, end=end, creator=consumer, user=consumer, short_notice=False)
		area.maximum_reservations_per_day = 1
		area.minimum_usage_block_time = None
		area._maximum_usage_block_time = None
		area.save()
		data = self.get_reservation_data(start + timedelta(hours=2), end + timedelta(hours=2), area)
		response = self.client.post(reverse('create_reservation'), data, follow=True)
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "You may only have 1 reservations for this area per day. Missed reservations are included when counting the number of reservations per day")

		# even if the first one was missed, still counts towards the limit
		first_of_the_day.missed = True
		first_of_the_day.save()
		data = self.get_reservation_data(start + timedelta(hours=2), end + timedelta(hours=2), area)
		response = self.client.post(reverse('create_reservation'), data, follow=True)
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "You may only have 1 reservations for this area per day. Missed reservations are included when counting the number of reservations per day")

		# test minimum time between reservations
		first_of_the_day.missed = False
		first_of_the_day.save()

		area.maximum_reservations_per_day = None
		area.minimum_time_between_reservations = 120
		area.save()
		data = self.get_reservation_data(start + timedelta(minutes=90), end + timedelta(minutes=90), area)
		response = self.client.post(reverse('create_reservation'), data, follow=True)
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Separate reservations for this area that belong to you must be at least 120 minutes apart from each other. The proposed reservation ends too close to another reservation.")

		data = self.get_reservation_data(start + timedelta(minutes=30), start + timedelta(minutes=90), area)
		response = self.client.post(reverse('create_reservation'), data, follow=True)
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Separate reservations for this area that belong to you must be at least 120 minutes apart from each other. The proposed reservation begins too close to another reservation.")
		self.assertContains(response, "Separate reservations for this area that belong to you must be at least 120 minutes apart from each other. The proposed reservation ends too close to another reservation.")
		self.assertContains(response, "Separate reservations for this area that belong to you must be at least 120 minutes apart from each other. The proposed reservation ends too close to another reservation.")

		area.maximum_future_reservation_time = 90
		area.minimum_time_between_reservations = None
		area.save()
		data = self.get_reservation_data(start + timedelta(minutes=90), end + timedelta(minutes=90), area)
		response = self.client.post(reverse('create_reservation'), data, follow=True)
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "You may only reserve up to 90 minutes of time on this area, starting from the current time onward.")

		first_of_the_day.delete()

	def test_create_reservation(self):
		start = datetime.now() + timedelta(hours=1)
		end = start + timedelta(hours=1)
		data = self.get_reservation_data(start, end, area)

		login_as(self.client, consumer)
		response = self.client.post(reverse('create_reservation'), data, follow=True)
		self.assertEqual(response.status_code, 200)
		self.assertEqual(Reservation.objects.all().count(), 1)
		self.assertTrue(Reservation.objects.get(area=area))

	def test_create_reservation_multi_projects(self):
		start = datetime.now() + timedelta(hours=1)
		end = start + timedelta(hours=1)
		data = self.get_reservation_data(start, end, area)

		login_as(self.client, consumer)

		second_project = Project.objects.create(name="project2", account=Account.objects.get(name='account1'))
		consumer.projects.add(second_project)

		# test creating reservation on a project the user is not associated with (trying to bill another project)
		not_my_project = Project.objects.create(name="not my project", account=Account.objects.get(name="account1"))
		data['project_id'] = not_my_project.id
		response = self.client.post(reverse('create_reservation'), data, follow=True)
		self.assertEqual(response.status_code, 200)
		self.assertEqual(Reservation.objects.all().count(), 0)
		self.assertContains(response, "Associate your reservation with a project.")

		# test not sending project id
		data['project_id'] = ''
		response = self.client.post(reverse('create_reservation'), data, follow=True)
		self.assertEqual(response.status_code, 200)
		self.assertEqual(Reservation.objects.all().count(), 0)
		self.assertContains(response, "Associate your reservation with a project.")

		data['project_id'] = second_project.id
		response = self.client.post(reverse('create_reservation'), data, follow=True)
		self.assertEqual(response.status_code, 200)
		self.assertEqual(Reservation.objects.all().count(), 1)
		self.assertTrue(Reservation.objects.get(area=area))

	def test_create_reservation_for_somebody_else(self):
		start = datetime.now() + timedelta(hours=1)
		end = start + timedelta(hours=1)
		data = self.get_reservation_data(start, end, area)
		data['impersonate'] = consumer.id

		login_as(self.client, staff)
		response = self.client.post(reverse('create_reservation'), data, follow=True)
		self.assertEqual(response.status_code, 200)
		self.assertEqual(Reservation.objects.all().count(), 1)
		self.assertTrue(Reservation.objects.get(area=area))
		self.assertEqual(Reservation.objects.get(area=area).user, consumer)
		self.assertEqual(Reservation.objects.get(area=area).creator, staff)

	def test_resize_reservation(self):
		# create reservation
		start = datetime.now() + timedelta(hours=1)
		end = start + timedelta(hours=1)
		data = self.get_reservation_data(start, end, area)

		login_as(self.client, consumer)
		response = self.client.post(reverse('create_reservation'), data, follow=True)
		self.assertEqual(response.status_code, 200)
		reservation = Reservation.objects.get(area=area)
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
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Reservation start time')
		self.assertContains(response, 'must be before the end time')

		# test resize to end before now
		old_resa = Reservation.objects.create(area=area, start=datetime.now() - timedelta(hours=1), end=datetime.now() + timedelta(hours=1), creator=consumer, user=consumer, short_notice=False)
		response = self.client.post(reverse('resize_reservation'), {'delta': -65, 'id': old_resa.id}, follow=True)
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Reservation end time')
		self.assertContains(response, 'is earlier than the current time')
		old_resa.delete()

		# create a outage and try to resize reservation to overlap outage
		start_reservation = end + timedelta(hours=1)
		end_reservation = start_reservation + timedelta(hours=1)
		ScheduledOutage.objects.create(area=area, start=start_reservation, end=end_reservation, creator=staff)
		response = self.client.post(reverse('resize_reservation'), {'delta': 61, 'id': reservation.id}, follow=True)
		self.assertEquals(response.status_code, 200)
		self.assertContains(response, "Your reservation coincides with a scheduled outage. Please choose a different time.")

		# test reduce reservation time by 10 min
		response = self.client.post(reverse('resize_reservation'), {'delta': -10, 'id': reservation.id}, follow=True)
		self.assertEquals(response.status_code, 200)
		old_reservation = Reservation.objects.get(pk=reservation.id)
		self.assertTrue(old_reservation.cancelled)
		self.assertEquals(old_reservation.cancelled_by, consumer)
		self.assertEquals(Reservation.objects.filter(area=area, cancelled=False).count(), 1)
		new_reservation = list(Reservation.objects.filter(area=area, cancelled=False))[0]
		self.assertEquals(new_reservation.end, old_reservation.end - timedelta(minutes=10))

		# test resize cancelled reservation
		reservation = Reservation.objects.get(pk=reservation.id)
		response = self.client.post(reverse('resize_reservation'), {'delta': 10, 'id': reservation.id}, follow=True)
		self.assertContains(response, "This reservation has already been cancelled", status_code=400)

		# test increase reservation time by 10 min
		response = self.client.post(reverse('resize_reservation'), {'delta': 10, 'id': new_reservation.id}, follow=True)
		self.assertEquals(response.status_code, 200)
		old_reservation = Reservation.objects.get(pk=new_reservation.id)
		self.assertTrue(old_reservation.cancelled)
		self.assertEquals(old_reservation.cancelled_by, consumer)
		self.assertEquals(Reservation.objects.filter(area=area, cancelled=False).count(), 1)
		new_reservation = list(Reservation.objects.filter(area=area, cancelled=False))[0]
		self.assertEquals(new_reservation.end, old_reservation.end + timedelta(minutes=10))
		new_reservation.delete()

		# test increase reservation time by 10 min while logged in
		older_resa_still_ongoing = Reservation.objects.create(area=area, start=datetime.now() - timedelta(hours=1), end=datetime.now() + timedelta(hours=1), user=consumer, creator=consumer, missed=False, short_notice=False)
		AreaAccessRecord.objects.create(area=area, customer=consumer, start=datetime.now(), project=project)
		response = self.client.post(reverse('resize_reservation'), {'delta': 10, 'id': older_resa_still_ongoing.id}, follow=True)
		self.assertEquals(response.status_code, 200)
		old_reservation = Reservation.objects.get(pk=older_resa_still_ongoing.id)
		self.assertTrue(old_reservation.cancelled)
		self.assertEquals(old_reservation.cancelled_by, consumer)
		self.assertEquals(Reservation.objects.filter(area=area, cancelled=False).count(), 1)
		new_reservation = list(Reservation.objects.filter(area=area, cancelled=False))[0]
		self.assertEquals(new_reservation.end, old_reservation.end + timedelta(minutes=10))
		self.assertEquals(new_reservation.start, old_reservation.start)
		new_reservation.delete()

		# test decrease reservation time by 10 min while logged in
		older_resa_still_ongoing = Reservation.objects.create(area=area, start=datetime.now() - timedelta(hours=1), end=datetime.now() + timedelta(hours=1), user=consumer, creator=consumer, missed=False, short_notice=False)
		AreaAccessRecord.objects.create(area=area, customer=consumer, start=datetime.now(), project=project)
		response = self.client.post(reverse('resize_reservation'), {'delta': -10, 'id': older_resa_still_ongoing.id}, follow=True)
		self.assertEquals(response.status_code, 200)
		old_reservation = Reservation.objects.get(pk=older_resa_still_ongoing.id)
		self.assertTrue(old_reservation.cancelled)
		self.assertEquals(old_reservation.cancelled_by, consumer)
		self.assertEquals(Reservation.objects.filter(area=area, cancelled=False).count(), 1)
		new_reservation = list(Reservation.objects.filter(area=area, cancelled=False))[0]
		self.assertEquals(new_reservation.end, old_reservation.end - timedelta(minutes=10))
		self.assertEquals(new_reservation.start, old_reservation.start)

	def test_move_reservation(self):
		# create reservation
		start = datetime.now() + timedelta(hours=1)
		end = start + timedelta(hours=1)
		data = self.get_reservation_data(start, end, area)

		login_as(self.client, consumer)
		response = self.client.post(reverse('create_reservation'), data, follow=True)
		self.assertEquals(response.status_code, 200)
		reservation = Reservation.objects.get(area=area)
		self.assertTrue(reservation.id)

		# test wrong delta
		response = self.client.post(reverse('move_reservation'), {'delta': 'asd', 'id': reservation.id}, follow=True)
		self.assertEquals(response.status_code, 400)
		self.assertEquals(response.content.decode(), "Invalid delta")

		# test no reservation id
		response = self.client.post(reverse('move_reservation'), {'delta': 10}, follow=True)
		self.assertEquals(response.status_code, 404)
		self.assertEquals(response.content.decode(), "The reservation that you wish to modify doesn't exist!")

		# create a outage and try to move reservation to overlap outage
		start_reservation = end + timedelta(hours=1)
		end_reservation = start_reservation + timedelta(hours=1)
		ScheduledOutage.objects.create(area=area, start=start_reservation, end=end_reservation, creator=staff)
		response = self.client.post(reverse('move_reservation'), {'delta': 61, 'id': reservation.id}, follow=True)
		self.assertEquals(response.status_code, 200)
		self.assertContains(response, "Your reservation coincides with a scheduled outage. Please choose a different time.")

		# test move reservation while logged in area
		older_resa_still_ongoing = Reservation.objects.create(area=area, start=datetime.now() - timedelta(hours=1), end=datetime.now() + timedelta(hours=1), user=consumer, creator=consumer, missed=False, short_notice=False)
		area_access_record = AreaAccessRecord.objects.create(area=area, customer=consumer, start=datetime.now(), project=project)
		response = self.client.post(reverse('move_reservation'), {'delta': -10, 'id': older_resa_still_ongoing.id}, follow=True)
		self.assertEquals(response.status_code, 400)
		self.assertEquals(response.content.decode(), "You may only resize an area reservation while logged in that area.")
		area_access_record.delete()
		older_resa_still_ongoing.delete()

		# test move reservation 10 min earlier
		response = self.client.post(reverse('move_reservation'), {'delta': -10, 'id': reservation.id}, follow=True)
		self.assertEquals(response.status_code, 200)
		old_reservation = Reservation.objects.get(pk=reservation.id)
		self.assertTrue(old_reservation.cancelled)
		self.assertEquals(old_reservation.cancelled_by, consumer)
		self.assertEquals(Reservation.objects.filter(area=area, cancelled=False).count(), 1)
		new_reservation = list(Reservation.objects.filter(area=area, cancelled=False))[0]
		self.assertEquals(new_reservation.end, old_reservation.end - timedelta(minutes=10))
		self.assertEquals(new_reservation.start, old_reservation.start - timedelta(minutes=10))

		# test move cancelled reservation
		reservation = Reservation.objects.get(pk=reservation.id)
		response = self.client.post(reverse('move_reservation'), {'delta': 10, 'id': reservation.id}, follow=True)
		self.assertContains(response, "This reservation has already been cancelled", status_code=400)

		# test move new reservation 10 min later
		response = self.client.post(reverse('move_reservation'), {'delta': 10, 'id': new_reservation.id}, follow=True)
		self.assertEquals(response.status_code, 200)
		old_reservation = Reservation.objects.get(pk=new_reservation.id)
		self.assertTrue(old_reservation.cancelled)
		self.assertEquals(old_reservation.cancelled_by, consumer)
		self.assertEquals(Reservation.objects.filter(area=area, cancelled=False).count(), 1)
		new_reservation = list(Reservation.objects.filter(area=area, cancelled=False))[0]
		self.assertEquals(new_reservation.end, old_reservation.end + timedelta(minutes=10))
		self.assertEquals(new_reservation.start, old_reservation.start + timedelta(minutes=10))

	def test_cancel_reservation(self):
		# create reservation
		start = datetime.now() + timedelta(hours=1)
		end = start + timedelta(hours=1)
		data = self.get_reservation_data(start, end, area)

		login_as(self.client, consumer)
		response = self.client.post(reverse('create_reservation'), data, follow=True)
		self.assertEquals(response.status_code, 200)
		reservation = Reservation.objects.get(area=area)
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
		missed_resa = Reservation.objects.create(area=area, start=start+timedelta(days=1), end=end+timedelta(days=1), user=consumer, creator=consumer, missed=True, short_notice=False)
		response = self.client.post(reverse('cancel_reservation', kwargs={'reservation_id': missed_resa.id}), {}, follow=True)
		self.assertEquals(response.status_code, 400)
		self.assertEquals(response.content.decode(), "This reservation was missed and cannot be modified.")

		# test cancel already ended reservation
		already_ended_resa = Reservation.objects.create(area=area, start=start - timedelta(days=1), end=end - timedelta(days=1), user=consumer, creator=consumer, missed=False, short_notice=False)
		response = self.client.post(reverse('cancel_reservation', kwargs={'reservation_id': already_ended_resa.id}), {}, follow=True)
		self.assertEquals(response.status_code, 400)
		self.assertEquals(response.content.decode(), "You may not cancel reservations that have already ended.")

		# test cancel reservation while logged in area
		older_resa_still_ongoing = Reservation.objects.create(area=area, start=datetime.now() - timedelta(hours=1), end=datetime.now() + timedelta(hours=1), user=consumer, creator=consumer, missed=False, short_notice=False)
		AreaAccessRecord.objects.create(area=area, customer=consumer, start=datetime.now(), project=project)
		response = self.client.post(reverse('cancel_reservation', kwargs={'reservation_id': older_resa_still_ongoing.id}), {}, follow=True)
		self.assertEquals(response.status_code, 400)
		self.assertEquals(response.content.decode(), "You may not cancel an area reservation while logged in that area.")

		# cancel reservation
		response = self.client.post(reverse('cancel_reservation', kwargs={'reservation_id': reservation.id}), {}, follow=True)
		self.assertEquals(response.status_code, 200)
		self.assertTrue(Reservation.objects.get(pk=reservation.id).cancelled)
		self.assertEquals(Reservation.objects.get(pk=reservation.id).cancelled_by, consumer)

		# test cancel already cancelled reservation
		response = self.client.post(reverse('cancel_reservation', kwargs={'reservation_id': reservation.id}), {}, follow=True)
		self.assertContains(response, "This reservation has already been cancelled by ", status_code=400)

		# test staff cancelling somebody else's reservation
		other_resa = Reservation.objects.create(area=area, start=start - timedelta(days=1),	end=end - timedelta(days=1), user=consumer, creator=consumer, short_notice=False)
		login_as(self.client, staff)
		response = self.client.post(reverse('cancel_reservation', kwargs={'reservation_id': other_resa.id}), {}, follow=True)
		self.assertContains(response, "You must provide a reason when cancelling someone else's reservation.", status_code=400)

		response = self.client.post(reverse('cancel_reservation', kwargs={'reservation_id': other_resa.id}), {'reason': 'reason'}, follow=True)
		self.assertEquals(response.status_code, 200)
		self.assertTrue(Reservation.objects.get(pk=other_resa.id).cancelled)
		self.assertEquals(Reservation.objects.get(pk=other_resa.id).cancelled_by, staff)

	def test_reservation_details(self):
		# create reservation
		start = datetime.now() + timedelta(hours=1)
		end = start + timedelta(hours=1)
		data = self.get_reservation_data(start, end, area)

		login_as(self.client, consumer)
		response = self.client.post(reverse('create_reservation'), data, follow=True)
		self.assertEquals(response.status_code, 200)
		reservation = Reservation.objects.get(area=area)
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

	def test_reservation_with_area_configuration(self):
		# TODO: create those tests
		self.assertTrue(True)

	def test_reservation_policy_off(self):
		# TODO: create those tests
		self.assertTrue(True)

	def test_reservation_success(self):
		# create reservation
		start = datetime.now() + timedelta(hours=1)
		end = start + timedelta(hours=1)
		data = self.get_reservation_data(start, end, area)

		login_as(self.client, consumer)
		response = self.client.post(reverse('create_reservation'), data, follow=True)
		self.assertEquals(response.status_code, 200)
		reservation = Reservation.objects.get(area=area)
		self.assertTrue(reservation.id)

		area.reservation_warning = 1
		area.save()
		response = self.client.post(reverse('move_reservation'), {'delta': 10, 'id': reservation.id}, follow=True)
		self.assertEquals(response.status_code, 201)



