from datetime import date, datetime, timedelta
from typing import Optional

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from NEMO.forms import RecurringConsumableChargeForm
from NEMO.models import Consumable, ConsumableWithdraw, RecurringConsumableCharge, Tool, UsageEvent, User
from NEMO.tests.test_utilities import NEMOTestCaseMixin, create_user_and_project
from NEMO.utilities import RecurrenceFrequency, beginning_of_the_day, format_datetime, get_recurring_rule
from NEMO.views.consumables import make_withdrawal
from NEMO.views.customization import (
    ApplicationCustomization,
    RecurringChargesCustomization,
)

consumable: Optional[Consumable] = None
supply: Optional[Consumable] = None


class ConsumableTestCase(NEMOTestCaseMixin, TestCase):
    def setUp(self):
        global consumable, supply
        consumable = Consumable.objects.create(
            name="Consumable", quantity=10, reminder_threshold=5, reminder_email="test@test.com"
        )
        supply = Consumable.objects.create(name="Consumable", quantity=1, reusable=True)

    def test_get(self):
        self.login_as_staff()
        self.client.get(reverse("consumables"), follow=True)

    def test_post(self):
        quantity = consumable.quantity
        data = {}
        self.login_as_staff()
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

    def test_withdrawal_not_allowed(self):
        customer, customer_project = create_user_and_project()
        staff, staff_project = create_user_and_project(is_staff=True)
        customer_project.allow_consumable_withdrawals = False
        customer_project.save()
        self.assertRaises(ValidationError, make_withdrawal, consumable.id, 1, customer_project.id, staff, customer.id)
        tool = Tool.objects.create(name="test_tool1", primary_owner=staff)
        start = timezone.now() - timedelta(hours=2)
        usage_event = UsageEvent.objects.create(
            user=customer, operator=customer, tool=tool, project=customer_project, start=start, end=timezone.now()
        )
        # However, it should always work for tool usage (otherwise the user cannot disable the tool)
        make_withdrawal(consumable.id, 1, customer_project.id, staff, customer.id, usage_event=usage_event)

    def test_post_self_checkout_not_allowed(self):
        # save consumable_user_self_checkout value
        consumable_user_self_checkout = ApplicationCustomization.get("consumable_user_self_checkout")
        try:
            ApplicationCustomization.set("consumable_user_self_checkout", "enabled")
            consumable_no_self_checkout = Consumable.objects.create(
                name="Consumable No Self Checkout",
                quantity=10,
                reminder_threshold=5,
                reminder_email="test@test.com",
                allow_self_checkout=False,
            )
            customer, customer_project = create_user_and_project()
            quantity = consumable_no_self_checkout.quantity
            self.login_as(customer)
            data = {
                "customer": customer.id,
                "project": customer_project.id,
                "consumable": consumable_no_self_checkout.id,
                "quantity": "1",
            }
            response = self.client.post(reverse("consumables"), data, follow=True)
            # Should fail because consumable is not tagged with allow_self_checkout = True
            self.assertEqual(response.status_code, 400)
            # Checkout, nothing should happen since the order did not go through
            response = self.client.post(reverse("withdraw_consumables"), follow=True)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(quantity, Consumable.objects.get(pk=consumable_no_self_checkout.id).quantity)
        finally:
            # restore consumable_user_self_checkout value
            ApplicationCustomization.set("consumable_user_self_checkout", consumable_user_self_checkout)

    def test_post_self_checkout_user_not_allowed(self):
        # save consumable_user_self_checkout value
        consumable_user_self_checkout = ApplicationCustomization.get("consumable_user_self_checkout")
        staff, staff_project = create_user_and_project(is_staff=True)
        try:
            ApplicationCustomization.set("consumable_user_self_checkout", "enabled")
            consumable_self_checkout = Consumable.objects.create(
                name="Consumable Self Checkout Only By User",
                quantity=10,
                reminder_threshold=5,
                reminder_email="test@test.com",
                allow_self_checkout=True,
            )
            consumable_self_checkout.self_checkout_only_users.set([staff])
            customer, customer_project = create_user_and_project()
            quantity = consumable_self_checkout.quantity
            self.login_as(customer)
            data = {
                "customer": customer.id,
                "project": customer_project.id,
                "consumable": consumable_self_checkout.id,
                "quantity": "1",
            }
            response = self.client.post(reverse("consumables"), data, follow=True)
            # Should fail because consumable is only available to staff user
            self.assertEqual(response.status_code, 400)
            # Checkout, nothing should happen since the order did not go through
            response = self.client.post(reverse("withdraw_consumables"), follow=True)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(quantity, Consumable.objects.get(pk=consumable_self_checkout.id).quantity)
            consumable_self_checkout.self_checkout_only_users.set([customer])
            response = self.client.post(reverse("consumables"), data, follow=True)
            # Should work now for customer
            self.assertEqual(response.status_code, 200)
            # Checkout, it should go through
            response = self.client.post(reverse("withdraw_consumables"), follow=True)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(quantity - 1, Consumable.objects.get(pk=consumable_self_checkout.id).quantity)
            # Should also still work for staff
            self.login_as(staff)
            response = self.client.post(reverse("consumables"), data, follow=True)
            self.assertEqual(response.status_code, 200)
            # Checkout, it should go through
            response = self.client.post(reverse("withdraw_consumables"), follow=True)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(quantity - 2, Consumable.objects.get(pk=consumable_self_checkout.id).quantity)
        finally:
            # restore consumable_user_self_checkout value
            ApplicationCustomization.set("consumable_user_self_checkout", consumable_user_self_checkout)

    def test_clean(self):
        test_consumable = Consumable()
        self.validate_model_error(test_consumable, ["name", "quantity"])
        test_consumable.name = "consumable"
        test_consumable.quantity = 10
        # Reusable item doesn't need anything else
        test_consumable.reusable = True
        test_consumable.full_clean()
        # Not reusable item requires both reminder threshold and reminder email
        test_consumable.reusable = False
        self.validate_model_error(test_consumable, ["reminder_threshold", "reminder_email"], strict=True)
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
        now = timezone.now()
        make_withdrawal(consumable.id, 1, user_project.id, staff, user.id)
        self.assertTrue(
            ConsumableWithdraw.objects.filter(
                date__gte=now, customer=user, project=user_project, merchant=staff, consumable=consumable, quantity=1
            ).exists()
        )
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

    def test_single_recurrence(self):
        # every day for one day
        rule_1 = get_recurring_rule(date.today(), RecurrenceFrequency.DAILY, count=1)
        rule_2 = get_recurring_rule(date.today(), RecurrenceFrequency.DAILY, until=date.today())
        today = beginning_of_the_day(datetime.now(), in_local_timezone=False)
        self.assertEqual(rule_1.after(today, inc=True), today)
        self.assertEqual(rule_2.after(today, inc=True), today)
        self.assertEqual(len(list(rule_1)), 1)
        self.assertEqual(len(list(rule_2)), 1)

    def test_recurrences(self):
        # every day until the end of time
        rule = get_recurring_rule(date.today(), RecurrenceFrequency.DAILY)
        today = beginning_of_the_day(datetime.now(), in_local_timezone=False)
        next_occurrence = rule.after(today, inc=True)
        self.assertEqual(next_occurrence, today)

    def test_validation(self):
        user, project = create_user_and_project(is_staff=False)
        staff, staff_project = create_user_and_project(is_staff=True)
        rec_charge = RecurringConsumableCharge()
        rec_charge: RecurringConsumableCharge = RecurringConsumableChargeForm(instance=rec_charge).save(commit=False)
        self.validate_model_error(rec_charge, ["name", "consumable", "last_updated_by", "last_updated"])
        rec_charge.name = "rec charge 1"
        rec_charge.consumable = consumable
        rec_charge.last_updated_by = staff
        rec_charge.last_updated = timezone.now()
        # all good now
        rec_charge.full_clean()
        # non-empty recurring charge i.e. with customer or project etc. should fail
        rec_charge.customer = user
        self.validate_model_error(rec_charge, ["project", "rec_start", "rec_frequency"], strict=True)
        rec_charge.project = project
        rec_charge.rec_start = date.today()
        self.validate_model_error(rec_charge, ["rec_frequency"])
        rec_charge.rec_frequency = RecurrenceFrequency.DAILY.value
        rec_charge.rec_count = 2
        rec_charge.rec_until = date.today()
        self.validate_model_error(rec_charge, ["__all__"])
        rec_charge.rec_until = None
        project.active = False
        project.save()
        user.is_active = False
        user.save()
        self.validate_model_error(rec_charge, ["project", "customer"])
        project.active = True
        project.save()
        user.is_active = True
        user.save()
        project.allow_consumable_withdrawals = False
        project.save()
        self.validate_model_error(rec_charge, ["project"])
        self.assertRaises(ValidationError, rec_charge.charge)
        project.allow_consumable_withdrawals = True
        project.save()
        # Now it should go through
        self.assertFalse(RecurringConsumableCharge.objects.exists())
        rec_charge.save()
        self.assertTrue(RecurringConsumableCharge.objects.exists())
        now = timezone.now()
        # Calling the management command should trigger the charge
        call_command("manage_recurring_charges")
        self.assertTrue(
            ConsumableWithdraw.objects.filter(
                date__gte=now, customer=user, project=project, merchant=staff, consumable=consumable, quantity=1
            ).exists()
        )

    def test_save_and_charge(self):
        # Test save and charge when empty or not
        user, project = create_user_and_project()
        data = {
            "save_and_charge": True,
            "name": "Bin #1",
            "quantity": 1,
            "rec_interval": 1,
        }
        staff = self.login_as_user_office()
        response = self.client.post(reverse("create_recurring_charge"), data, follow=True)
        # Validation error, Consumable is required
        self.assertFormError(response, "form", "consumable", "This field is required.")
        data["consumable"] = consumable.id
        response = self.client.post(reverse("create_recurring_charge"), data, follow=True)
        # Validation error. Customer is required when charging
        self.assertFormError(response, "form", "customer", "This field is required when charging.")
        data["customer"] = user.id
        response = self.client.post(reverse("create_recurring_charge"), data, follow=True)
        self.assertFormError(response, "form", "project", "This field is required.")
        self.assertFormError(response, "form", "rec_frequency", "This field is required.")
        self.assertFormError(response, "form", "rec_start", "This field is required.")
        data["project"] = project.id
        data["rec_frequency"] = RecurrenceFrequency.DAILY.value
        data["rec_start"] = format_datetime(datetime.now().date() + timedelta(days=5))
        response = self.client.post(reverse("create_recurring_charge"), data, follow=True)
        self.assertRedirects(response, reverse("recurring_charges"))
        self.assertTrue(
            RecurringConsumableCharge.objects.filter(
                consumable=consumable, customer=user, project=project, quantity=1
            ).exists()
        )
        recurring_charge = RecurringConsumableCharge.objects.filter(
            consumable=consumable, customer=user, project=project, quantity=1
        ).first()
        withdraw = ConsumableWithdraw.objects.filter(
            consumable=consumable, customer=user, project=project, quantity=1
        ).latest("date")
        self.assertIsNotNone(withdraw)
        # Charged less than 2 second ago, but still before now
        self.assertLess(timezone.now() - timedelta(seconds=2), withdraw.date)
        self.assertLess(withdraw.date, timezone.now())
        # Try editing and charging again on the same day
        response = self.client.post(reverse("edit_recurring_charge", args=[recurring_charge.id]), data, follow=True)
        self.assertRedirects(response, reverse("recurring_charges"))
        new_withdraw = ConsumableWithdraw.objects.filter(
            consumable=consumable, customer=user, project=project, quantity=1
        ).latest("date")
        # There is no new withdraw, it should be the same as previous since you cannot charge twice the same day
        self.assertEqual(withdraw.id, new_withdraw.id)
        self.assertEqual(withdraw.date, new_withdraw.date)

    def test_edit_when_locked(self):
        RecurringChargesCustomization.set("recurring_charges_lock", "enabled")
        user, project = create_user_and_project()
        new_user, new_project = create_user_and_project()
        charge = RecurringConsumableCharge()
        charge.name = "Bin #1"
        charge.customer = user
        charge.project = project
        charge.consumable = consumable
        charge.rec_start = datetime.now().date()
        charge.rec_frequency = RecurrenceFrequency.DAILY.value
        charge.save_with_user(user)
        data = {
            "name": "new name",
            "customer": new_user.id,
            "project": new_project.id,
            "consumable": supply.id,
            "quantity": 1,
            "rec_start": format_datetime(charge.rec_start + timedelta(days=5)),
            "rec_count": 5,
            "rec_frequency": RecurrenceFrequency.WEEKLY.value,
            "rec_interval": 1,
        }
        # Cannot edit as regular user
        self.login_as_user()
        response = self.client.post(reverse("edit_recurring_charge", args=[charge.id]), data, follow=True)
        self.assert_response_is_landing_page(response)
        # Login as staff now
        staff = self.login_as_user_office()
        response = self.client.post(reverse("edit_recurring_charge", args=[charge.id]), data, follow=True)
        self.assertTrue("edit_recurring_charge" not in response.request["PATH_INFO"])
        self.assertEqual(response.status_code, 200)
        # Only customer and project can change
        new_charge = RecurringConsumableCharge.objects.get(pk=charge.id)
        self.assertEqual(new_charge.customer, new_user)
        self.assertEqual(new_charge.project, new_project)
        self.assertEqual(charge.consumable, new_charge.consumable)
        self.assertEqual(charge.rec_start, new_charge.rec_start)
        self.assertEqual(charge.rec_frequency, new_charge.rec_frequency)
        self.assertEqual(charge.rec_count, new_charge.rec_count)
        # Check last updated by and last updated date
        self.assertEqual(new_charge.last_updated_by, staff)
        self.assertNotEqual(charge.last_updated, new_charge.last_updated)

    def test_edit_when_locked_facility_manager(self):
        RecurringChargesCustomization.set("recurring_charges_lock", "enabled")
        user, project = create_user_and_project()
        new_user, new_project = create_user_and_project()
        charge = RecurringConsumableCharge()
        charge.name = "Bin #1"
        charge.customer = user
        charge.project = project
        charge.consumable = consumable
        charge.rec_start = datetime.now().date()
        charge.rec_frequency = RecurrenceFrequency.DAILY.value
        charge.save_with_user(user)
        data = {
            "name": "new name",
            "customer": new_user.id,
            "project": new_project.id,
            "consumable": supply.id,
            "quantity": 1,
            "rec_start": format_datetime(charge.rec_start + timedelta(days=5)),
            "rec_count": 5,
            "rec_frequency": RecurrenceFrequency.WEEKLY.value,
            "rec_interval": 1,
        }
        staff = self.login_as_staff()
        # Change staff user to facility manager who can edit everything
        staff.is_facility_manager = True
        staff.save()
        self.login_as(staff)
        response = self.client.post(reverse("edit_recurring_charge", args=[charge.id]), data, follow=True)
        self.assertTrue("edit_recurring_charge" not in response.request["PATH_INFO"])
        # Everything should have changed now
        new_charge = RecurringConsumableCharge.objects.get(pk=charge.id)
        self.assertEqual(new_charge.name, "new name")
        self.assertEqual(new_charge.customer, new_user)
        self.assertEqual(new_charge.project, new_project)
        self.assertEqual(new_charge.consumable, supply)
        self.assertEqual(new_charge.rec_start, (datetime.now() + timedelta(days=5)).date())
        self.assertEqual(new_charge.rec_frequency, RecurrenceFrequency.WEEKLY.value)
        self.assertEqual(new_charge.rec_count, 5)
        self.assertEqual(new_charge.last_updated_by, staff)
        self.assertNotEqual(charge.last_updated, new_charge.last_updated)

    def test_create_when_locked(self):
        RecurringChargesCustomization.set("recurring_charges_lock", "enabled")
        self.login_as_user()
        response = self.client.get(reverse("create_recurring_charge"), follow=True)
        self.assert_response_is_landing_page(response)
        self.login_as_staff()
        response = self.client.get(reverse("create_recurring_charge"), follow=True)
        self.assert_response_is_landing_page(response)

    def test_delete_when_locked(self):
        RecurringChargesCustomization.set("recurring_charges_lock", "enabled")
        self.login_as_user()
        response = self.client.get(reverse("delete_recurring_charge", args=[1]), follow=True)
        self.assert_response_is_landing_page(response)
        self.login_as_staff()
        response = self.client.get(reverse("delete_recurring_charge", args=[1]), follow=True)
        self.assert_response_is_landing_page(response)

    def test_clear_recurring_charge(self):
        user, project = create_user_and_project()
        charge = RecurringConsumableCharge()
        charge.name = "Bin #1"
        charge.customer = user
        charge.project = project
        charge.consumable = consumable
        charge.rec_start = datetime.now().date()
        charge.rec_frequency = RecurrenceFrequency.DAILY.value
        charge.save_with_user(user)
        charge = RecurringConsumableCharge.objects.get(pk=charge.pk)
        self.assertIsNotNone(charge.customer)
        self.assertIsNotNone(charge.project)
        self.login_as_user_office()
        response = self.client.get(reverse("clear_recurring_charge", args=[charge.id]))
        self.assertRedirects(response, reverse("recurring_charges"))
        charge = RecurringConsumableCharge.objects.get(pk=charge.pk)
        self.assertIsNone(charge.customer)
        self.assertIsNone(charge.project)

    def login_as_user_office(self) -> User:
        tester, created = User.objects.get_or_create(
            username="test_staff", first_name="Test", last_name="Staff", is_user_office=True, badge_number=999999
        )
        self.login_as(tester)
        return tester
