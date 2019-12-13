import time

from django.test import TestCase
from django.urls import reverse

from NEMO.models import Tool, InterlockCardCategory, InterlockCard, Interlock, User, Door, Area, PhysicalAccessLevel, \
	Project, Account
from NEMO.tests.test_utilities import login_as_staff, login_as_user, test_response_is_login_page, \
	test_response_is_landing_page, login_as_user_with_permissions


class AreaAccessGetTestCase(TestCase):
	def test_area_access_page_by_staff(self):
		login_as_staff(self.client)
		response = self.client.post(reverse('area_access'), {}, follow=True)
		self.assertEquals(response.status_code, 405) # POST isn't accepted, only GET
		response = self.client.get(reverse('area_access'), {}, follow=True)
		self.assertTrue("area_access" in response.request['PATH_INFO'])
		self.assertEquals(response.status_code, 200)

	def test_area_access_page_by_user(self):
		login_as_user(self.client)
		response = self.client.get(reverse('area_access'), {}, follow=True)
		test_response_is_landing_page(self, response) # since user is not staff, it should redirect to landing

	def test_area_access_page_by_anonymous(self):
		response = self.client.get(reverse('area_access'), {}, follow=True)
		test_response_is_login_page(self, response)


class InAndOutScreensAreaAccess(TestCase):
	door: Door = None

	def setUp(self):
		global door
		interlock_card_category = InterlockCardCategory.objects.get(key='stanford')
		interlock_card = InterlockCard.objects.create(server="server.com", port=80, number=1, even_port=1, odd_port=2,
													  category=interlock_card_category)
		interlock = Interlock.objects.create(card=interlock_card, channel=1)
		area = Area.objects.create(name="Cleanroom", welcome_message="Welcome to the cleanroom")
		door = Door.objects.create(name='test_door', area=area, interlock=interlock)

	def test_welcome_screen_fails(self):
		response = self.client.post(reverse('welcome_screen', kwargs={'door_id':door.id}), follow=True)
		test_response_is_login_page(self, response)
		login_as_user(self.client)
		response = self.client.post(reverse('welcome_screen', kwargs={'door_id': door.id}), follow=True)
		test_response_is_landing_page(self, response) # landing since we don't have the right credentials
		login_as_user_with_permissions(self.client, ['add_areaaccessrecord'])
		response = self.client.post(reverse('welcome_screen', kwargs={'door_id': door.id}), follow=True)
		self.assertEquals(response.status_code, 405)  # POST isn't accepted, only GET
		response = self.client.get(reverse('welcome_screen', kwargs={'door_id': 999}), follow=True)
		self.assertEquals(response.status_code, 404)  # wrong door id

		response = self.client.get(reverse('welcome_screen', kwargs={'door_id': door.id}), follow=True)
		self.assertEquals(response.status_code, 200)  # All good now
		self.assertTrue("welcome_screen" in response.request['PATH_INFO'])

	def test_farewell_screen_fails(self):
		response = self.client.post(reverse('farewell_screen', kwargs={'door_id':door.id}), follow=True)
		test_response_is_login_page(self, response)
		login_as_user(self.client)
		response = self.client.post(reverse('farewell_screen', kwargs={'door_id': door.id}), follow=True)
		test_response_is_landing_page(self, response) # landing since we don't have the right credentials
		login_as_user_with_permissions(self.client, ['change_areaaccessrecord'])
		response = self.client.post(reverse('farewell_screen', kwargs={'door_id': door.id}), follow=True)
		self.assertEquals(response.status_code, 405)  # POST isn't accepted, only GET
		response = self.client.get(reverse('farewell_screen', kwargs={'door_id': 999}), follow=True)
		self.assertEquals(response.status_code, 404)  # wrong door id

		response = self.client.get(reverse('farewell_screen', kwargs={'door_id': door.id}), follow=True)
		self.assertEquals(response.status_code, 200)  # All good now
		self.assertTrue("farewell_screen" in response.request['PATH_INFO'])


	def test_login_to_area(self):
		response = self.client.post(reverse('login_to_area', kwargs={'door_id': door.id}), follow=True)
		test_response_is_login_page(self, response)
		login_as_user(self.client)
		response = self.client.post(reverse('login_to_area', kwargs={'door_id': door.id}), follow=True)
		test_response_is_landing_page(self, response)  # landing since we don't have the right credentials
		user = login_as_user_with_permissions(self.client, ['add_areaaccessrecord'])
		response = self.client.get(reverse('login_to_area', kwargs={'door_id': door.id}), data={'badge_number': user.badge_number}, follow=True)
		self.assertEquals(response.status_code, 405)  # GET isn't accepted, only POST
		response = self.client.post(reverse('login_to_area', kwargs={'door_id': 999}), follow=True)
		self.assertEquals(response.status_code, 404)  # wrong door id
		response = self.client.post(reverse('login_to_area', kwargs={'door_id': door.id}), follow=True)
		self.assertTrue("Your badge wasn\\'t recognized" in str(response.content))
		response = self.client.post(reverse('login_to_area', kwargs={'door_id': door.id}), data={'badge_number':999}, follow=True)
		self.assertTrue("Your badge wasn\\'t recognized" in str(response.content))
		response = self.client.post(reverse('login_to_area', kwargs={'door_id': door.id}), data={'badge_number': user.badge_number}, follow=True)
		self.assertEquals(response.status_code, 200)
		self.assertTrue(f"login_to_area/{door.id}" in response.request['PATH_INFO'])
		self.assertTrue("Physical access denied" in str(response.content)) # user does not have access
		user.physical_access_levels.add(PhysicalAccessLevel.objects.create(name="cleanroom access", area=door.area, schedule=PhysicalAccessLevel.Schedule.ALWAYS))
		user.save()
		response = self.client.post(reverse('login_to_area', kwargs={'door_id': door.id}), data={'badge_number': user.badge_number}, follow=True)
		self.assertEquals(response.status_code, 200)
		self.assertTrue(f"login_to_area/{door.id}" in response.request['PATH_INFO'])
		self.assertTrue("You are not a member of any active projects" in str(response.content))  # user does not have active projects

		user.projects.add(Project.objects.create(name="Project1", account=Account.objects.create(name="Account1")))
		user.save()
		response = self.client.post(reverse('login_to_area', kwargs={'door_id': door.id}), data={'badge_number': user.badge_number}, follow=True)
		self.assertEquals(response.status_code, 200)
		self.assertTrue(f"login_to_area/{door.id}" in response.request['PATH_INFO'])
		self.assertTrue("You're logged in to the " in str(response.content))

class DoorInterlockTestCase(TestCase):
	door: Door = None
	interlock: Interlock = None

	def setUp(self):
		global door, interlock
		interlock_card_category = InterlockCardCategory.objects.get(key='stanford')
		interlock_card = InterlockCard.objects.create(server="server.com", port=80, number=1, even_port=1, odd_port=2, category=interlock_card_category)
		interlock = Interlock.objects.create(card=interlock_card, channel=1)
		owner = User.objects.create(username='mctest', first_name='Testy', last_name='McTester')
		door = Tool.objects.create(name='test_door', primary_owner=owner, interlock=interlock)

	def test_door(self):
		self.assertEquals(door.interlock.state, Interlock.State.UNKNOWN)

