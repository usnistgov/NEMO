from typing import Optional

from django.test.testcases import TestCase
from django.urls import reverse

from NEMO.models import Consumable
from NEMO.tests.test_utilities import create_user_and_project, login_as_staff, validate_model_error
from NEMO.views.consumables import make_withdrawal

consumable: Optional[Consumable] = None
supply: Optional[Consumable] = None


class ToolTestCase(TestCase):
	def setUp(self):
		global consumable, supply
		consumable = Consumable.objects.create(
			name="Consumable", quantity=10, reminder_threshold=5, reminder_email="test@test.com"
		)
		supply = Consumable.objects.create(name="Consumable", quantity=1, reusable=True)

	def test_get(self):
		login_as_staff(self.client)
		self.client.get(reverse("consumables"), follow=True)

	def test_post(self):
		quantity = consumable.quantity
		data = {}
		login_as_staff(self.client)
		response = self.client.post(reverse("consumables"), data, follow=True)
		self.assertEqual(response.status_code, 400)
		customer, customer_project = create_user_and_project()
		data = {"customer": customer.id, "project": customer_project.id, "consumable": consumable.id, "quantity": "1"}
		response = self.client.post(reverse("consumables"), data, follow=True)
		self.assertEqual(response.status_code, 200)
		# Quantity has not changed yet since we haven't checked out
		self.assertEqual(quantity, Consumable.objects.get(pk=consumable.id).quantity)
		# Add a second withdrawal order
		response = self.client.post(reverse("consumables"), data, follow=True)
		self.assertEqual(response.status_code, 200)
		# Remove first one from session
		response = self.client.get(reverse("remove_consumable", args=[1]), follow=True)
		self.assertEqual(response.status_code, 200)
		# Clear them all out
		response = self.client.get(reverse("clear_withdrawals"), follow=True)
		self.assertEqual(response.status_code, 200)
		# Checkout, nothing should happen since we cleared all orders
		response = self.client.post(reverse("withdraw_consumables"), follow=True)
		self.assertEqual(response.status_code, 200)
		self.assertEqual(quantity, Consumable.objects.get(pk=consumable.id).quantity)
		# Add again
		response = self.client.post(reverse("consumables"), data, follow=True)
		self.assertEqual(response.status_code, 200)
		# Checkout, now the withdrawal should have happened
		response = self.client.post(reverse("withdraw_consumables"), follow=True)
		self.assertEqual(response.status_code, 200)
		self.assertEqual(quantity - 1, Consumable.objects.get(pk=consumable.id).quantity)

	def test_clean(self):
		test_consumable = Consumable()
		validate_model_error(self, test_consumable, "name", "quantity")
		test_consumable.name = "consumable"
		test_consumable.quantity = 10
		# Reusable item doesn't need anything else
		test_consumable.reusable = True
		test_consumable.full_clean()
		# Not reusable item requires both reminder threshold and reminder email
		test_consumable.reusable = False
		validate_model_error(self, test_consumable, "reminder_threshold", "reminder_email")
		test_consumable.reminder_threshold = 5
		test_consumable.reminder_email = "test@test.com"
		test_consumable.full_clean()

	def test_consumable_withdrawal(self):
		consumable_quantity = consumable.quantity
		user, user_project = create_user_and_project(is_staff=False)
		staff, staff_project = create_user_and_project(is_staff=True)
		make_withdrawal(consumable.id, 1, user_project.id, staff, user.id)
		new_consumable = Consumable.objects.get(pk=consumable.id)
		self.assertEqual(new_consumable.quantity, consumable_quantity - 1)
		self.assertFalse(new_consumable.reminder_threshold_reached)
		self.assertEqual(
			new_consumable.reminder_threshold_reached, new_consumable.quantity < new_consumable.reminder_threshold
		)
		make_withdrawal(consumable.id, 4, user_project.id, staff, user.id)
		new_consumable = Consumable.objects.get(pk=consumable.id)
		self.assertEqual(new_consumable.quantity, consumable_quantity - 5)
		self.assertFalse(new_consumable.reminder_threshold_reached)
		self.assertEqual(
			new_consumable.reminder_threshold_reached, new_consumable.quantity < new_consumable.reminder_threshold
		)
		make_withdrawal(consumable.id, 1, user_project.id, staff, user.id)
		new_consumable = Consumable.objects.get(pk=consumable.id)
		self.assertEqual(new_consumable.quantity, consumable_quantity - 6)
		self.assertTrue(new_consumable.reminder_threshold_reached)
		self.assertEqual(
			new_consumable.reminder_threshold_reached, new_consumable.quantity < new_consumable.reminder_threshold
		)

	def test_supply_withdrawal(self):
		supply_quantity = supply.quantity
		user, user_project = create_user_and_project(is_staff=False)
		staff, staff_project = create_user_and_project(is_staff=True)
		make_withdrawal(supply.id, 1, user_project.id, staff, user.id)
		new_supply = Consumable.objects.get(pk=supply.id)
		# Supply quantity always stays the same, no matter how many are withdrawn
		self.assertEqual(new_supply.quantity, supply_quantity)
		# Threshold should never be reached
		self.assertFalse(new_supply.reminder_threshold_reached)
		make_withdrawal(supply.id, 4, user_project.id, staff, user.id)
		new_supply = Consumable.objects.get(pk=supply.id)
		self.assertEqual(new_supply.quantity, supply_quantity)
		self.assertFalse(new_supply.reminder_threshold_reached)
		make_withdrawal(supply.id, 1, user_project.id, staff, user.id)
		new_supply = Consumable.objects.get(pk=supply.id)
		self.assertEqual(new_supply.quantity, supply_quantity)
		self.assertFalse(new_supply.reminder_threshold_reached)
