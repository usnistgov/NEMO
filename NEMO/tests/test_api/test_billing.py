from datetime import datetime

from django.contrib.auth.models import Permission
from django.test import TestCase
from django.utils import timezone
from rest_framework import ISO_8601
from rest_framework.settings import api_settings

from NEMO.models import Account, Area, AreaAccessRecord, Project, Tool, UsageEvent, User
from NEMO.tests.test_utilities import login_as_staff


class BillingAPITestCase(TestCase):
	def setUp(self):
		# create a few usage events etc.
		owner1 = User.objects.create(username="mctest1", first_name="Testy", last_name="McTester")
		tool1 = Tool.objects.create(name="test_tool1", primary_owner=owner1)
		owner2 = User.objects.create(username="mctest2", first_name="Testy", last_name="McTester")
		tool2 = Tool.objects.create(name="test_tool2", primary_owner=owner2)

		account = Account.objects.create(name="Test Account")
		project = Project.objects.create(name="Test Project", account=account, application_identifier="N19.0001")
		UsageEvent.objects.create(
			operator=owner1,
			user=owner1,
			tool=tool1,
			project=project,
			end=datetime.now().astimezone(timezone.get_current_timezone()),
		)
		UsageEvent.objects.create(
			operator=owner2,
			user=owner2,
			tool=tool1,
			project=project,
			end=datetime.now().astimezone(timezone.get_current_timezone()),
		)
		UsageEvent.objects.create(
			operator=owner2,
			user=owner2,
			tool=tool2,
			project=project,
			end=datetime.now().astimezone(timezone.get_current_timezone()),
		)

		# create a few area access records
		area = Area.objects.create(name="Cleanroom", welcome_message="")
		AreaAccessRecord.objects.create(
			area=area, customer=owner2, project=project, end=datetime.now().astimezone(timezone.get_current_timezone())
		)

		# add staff charges, consumable, missed reservation, training

	def test_billing_by_username(self):
		self.billing_by_attribute("username", "mctest2", "username", 3)

	def test_billing_by_account_name(self):
		self.billing_by_attribute("account_name", "Test Account", "account", 4)

	def test_billing_by_account_id(self):
		self.billing_by_attribute("account_id", 1, "account_id", 4)

	def test_billing_by_project_name(self):
		self.billing_by_attribute("project_name", "Test Project", "project", 4)

	def test_billing_by_project_id(self):
		self.billing_by_attribute("project_id", 1, "project_id", 4)

	def test_billing_by_application_name(self):
		self.billing_by_attribute("application_name", "N19.0001", "application", 4)

	def billing_by_attribute(self, attribute_name, attribute_value, result_attribute_name, results_number):
		data = {
			"start": datetime.now().strftime("%m/%d/%Y"),
			"end": datetime.now().strftime("%m/%d/%Y"),
			attribute_name: attribute_value,
		}
		login_as_staff(self.client)

		response = self.client.get("/api/billing", data, follow=True)
		self.assertEqual(response.status_code, 403, "regular user or staff doesn't have permission")

		staff_user = User.objects.get(username="test_staff")
		staff_user.user_permissions.add(Permission.objects.get(codename="use_billing_api"))
		staff_user.save()
		response = self.client.get("/api/billing", data, follow=True)
		self.assertEqual(response.status_code, 200)
		self.assertEqual(len(response.data), results_number)

		date_format = (
			"%Y-%m-%dT%H:%M:%S.%f%z"
			if api_settings.DATETIME_FORMAT.lower() == ISO_8601
			else api_settings.DATETIME_FORMAT
		)
		for billing_item in response.data:
			start = datetime.strptime(billing_item["start"], date_format)
			end = datetime.strptime(billing_item["end"], date_format)
			self.assertEqual(datetime.now().date(), start.date())
			self.assertEqual(datetime.now().date(), end.date())
			self.assertEqual(billing_item.get(result_attribute_name), attribute_value)
