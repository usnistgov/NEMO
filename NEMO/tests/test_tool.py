from django.contrib.admin import AdminSite
from django.urls import reverse

from NEMO.admin import InterlockCardAdminForm, ToolAdminForm, ToolAdmin
from NEMO.models import InterlockCard, Interlock, User, Tool, InterlockCardCategory, Area, PhysicalAccessLevel, Project, \
	Account, Door
from django.test import TestCase

from NEMO.tests.test_utilities import login_as_user, login_as_staff, login_as_access_user, login_as


class ToolTestCase(TestCase):
	tool: Tool = None
	alternate_tool: Tool = None
	area_door: Door = None

	def setUp(self):
		# This also tests the admin forms for interlock card and tool
		global tool, alternate_tool, area_door
		interlock_category = InterlockCardCategory.objects.get(key='web_relay_http')
		interlock_card_data = {'server': 'example.com', 'port': 25, 'category': interlock_category.id}
		interlock_card_form = InterlockCardAdminForm(interlock_card_data)
		self.assertTrue(interlock_card_form.is_valid(), interlock_card_form.errors.as_text())
		interlock_card = interlock_card_form.save()
		interlock = Interlock.objects.create(card=interlock_card, channel=1)
		cleanroom_interlock = Interlock.objects.create(card=interlock_card, channel=2)
		owner = User.objects.create(username='mctest', first_name='Testy', last_name='McTester')
		cleanroom = Area.objects.create(name="cleanroom", welcome_message='Welcome')
		tool_data = {
			'name':'test_tool',
			'_category': 'test',
			'_location':'office',
			'_phone_number': '1234567890',
			'_primary_owner': owner.id,
			'_backup_owners': [owner.id],
			'_interlock': interlock.id,
			'_operational': False,
			'_notification_email_address': 'email@example.com',
			'_requires_area_access': cleanroom.id,
			'_grant_badge_reader_access_upon_qualification': "test",
			'_grant_physical_access_level_upon_qualification': PhysicalAccessLevel.objects.create(name="cleanroom access", schedule=PhysicalAccessLevel.Schedule.ALWAYS, area=cleanroom).id,
			'_reservation_horizon': 15,
			'_minimum_usage_block_time': 3,
			'_maximum_usage_block_time': 7,
			'_maximum_reservations_per_day': 2,
			'_minimum_time_between_reservations': 10,
			'_maximum_future_reservation_time': 20,
			'_missed_reservation_threshold': 30,
			'_allow_delayed_logoff': True,
			'_post_usage_questions': "Questions",
			'_policy_off_between_times': True,
			'_policy_off_start_time': "5:00 PM",
			'_policy_off_end_time': "4:00 PM",
			'_policy_off_weekend': True,
			'visible': True,
		}
		area_door = Door.objects.create(name="cleanroom door", area=cleanroom, interlock=cleanroom_interlock)
		tool_form = ToolAdminForm(tool_data)
		self.assertTrue(tool_form.is_valid(), tool_form.errors.as_text())
		tool = tool_form.save()
		alternate_tool_data = {'name':'alt_test_tool', 'parent_tool':tool.id, 'visible': True}
		alternate_tool_form = ToolAdminForm(alternate_tool_data)
		self.assertTrue(alternate_tool_form.is_valid(), alternate_tool_form.errors.as_text())
		alternate_tool = alternate_tool_form.save()

	def test_tool_and_parent_properties(self):
		self.assertNotEquals(tool.id, alternate_tool.id)
		self.assertNotEquals(tool.name, alternate_tool.name)
		self.assertFalse(alternate_tool.visible)
		self.assertTrue(tool.visible)
		self.assertTrue(tool.is_parent_tool())
		self.assertTrue(alternate_tool.is_child_tool())
		self.assertEquals(tool.category, alternate_tool.category)
		self.assertEquals(tool.operational, alternate_tool.operational)
		self.assertEquals(tool.primary_owner, alternate_tool.primary_owner)
		self.assertEquals(tool.backup_owners, alternate_tool.backup_owners)
		self.assertEquals(tool.location, alternate_tool.location)
		self.assertEquals(tool.phone_number, alternate_tool.phone_number)
		self.assertEquals(tool.notification_email_address, alternate_tool.notification_email_address)
		self.assertEquals(tool.interlock, alternate_tool.interlock)
		self.assertEquals(tool.requires_area_access, alternate_tool.requires_area_access)
		self.assertEquals(tool.grant_physical_access_level_upon_qualification, alternate_tool.grant_physical_access_level_upon_qualification)
		self.assertEquals(tool.grant_badge_reader_access_upon_qualification, alternate_tool.grant_badge_reader_access_upon_qualification)
		self.assertEquals(tool.reservation_horizon, alternate_tool.reservation_horizon)
		self.assertEquals(tool.minimum_usage_block_time, alternate_tool.minimum_usage_block_time)
		self.assertEquals(tool.maximum_usage_block_time, alternate_tool.maximum_usage_block_time)
		self.assertEquals(tool.maximum_reservations_per_day, alternate_tool.maximum_reservations_per_day)
		self.assertEquals(tool.minimum_time_between_reservations, alternate_tool.minimum_time_between_reservations)
		self.assertEquals(tool.maximum_future_reservation_time, alternate_tool.maximum_future_reservation_time)
		self.assertEquals(tool.missed_reservation_threshold, alternate_tool.missed_reservation_threshold)
		self.assertEquals(tool.allow_delayed_logoff, alternate_tool.allow_delayed_logoff)
		self.assertEquals(tool.post_usage_questions, alternate_tool.post_usage_questions)
		self.assertEquals(tool.policy_off_between_times, alternate_tool.policy_off_between_times)
		self.assertEquals(tool.policy_off_start_time, alternate_tool.policy_off_start_time)
		self.assertEquals(tool.policy_off_end_time, alternate_tool.policy_off_end_time)
		self.assertEquals(tool.policy_off_weekend, alternate_tool.policy_off_weekend)

		self.assertEquals(tool.get_absolute_url(), alternate_tool.get_absolute_url())


	def test_tool_in_use(self):
		user = login_as_user(self.client)
		# make the tool operational
		tool.operational = True
		tool.save()
		project = Project.objects.create(name="test project", application_identifier="sadasd", account=Account.objects.create(name="test account"))
		user.projects.add(project)
		# user needs to be qualified to use the tool
		user.qualifications.add(tool)
		user.physical_access_levels.add(PhysicalAccessLevel.objects.get(name="cleanroom access"))
		user.badge_number = 11
		user.training_required = False
		user.save()
		# log into the area
		login_as_access_user(self.client)
		response = self.client.post(reverse('login_to_area', kwargs={'door_id': area_door.id}), {'badge_number':user.badge_number}, follow=True)
		self.assertEquals(response.status_code, 200, response.content.decode())
		login_as(self.client, user)
		# start using tool
		response = self.client.post(reverse('enable_tool', kwargs={'tool_id':tool.id, 'user_id':user.id, 'project_id':project.id, 'staff_charge':'false'}), follow=True)
		self.assertEquals(response.status_code, 200, response.content.decode())
		# make sure both tool and child tool are "in use"
		self.assertTrue(tool.in_use())
		self.assertTrue(alternate_tool.in_use())
		# make sure both return the same usage event
		self.assertEquals(tool.get_current_usage_event(), alternate_tool.get_current_usage_event())