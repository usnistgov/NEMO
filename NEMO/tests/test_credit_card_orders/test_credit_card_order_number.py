from django.test import TestCase

from NEMO.apps.credit_card_orders.customization import CreditCardOrderCustomization
from NEMO.tests.test_utilities import create_user_and_project


class CreditCardOrderNumberTest(TestCase):

    def setUp(self):
        self.user, self.project = create_user_and_project()

    def test_next_credit_card_order_number(self):
        # Test easy cases, if auto numbering is not enabled, shouldn't return anything
        CreditCardOrderCustomization.set("credit_card_order_number_template_enabled", "")
        self.assertFalse(CreditCardOrderCustomization.next_credit_card_order_number(self.user))
        # Enabled but no template => nothing
        CreditCardOrderCustomization.set("credit_card_order_number_template_enabled", "enabled")
        CreditCardOrderCustomization.set("credit_card_order_number_template", "")
        self.assertFalse(CreditCardOrderCustomization.next_credit_card_order_number(self.user))
        # Enabled and simple template with current number
        CreditCardOrderCustomization.set("credit_card_order_number_template_enabled", "enabled")
        CreditCardOrderCustomization.set("credit_card_order_number_template", "{{ current_number }}")
        current_number = 1
        self.assertEqual(
            CreditCardOrderCustomization.next_credit_card_order_number(self.user, save=True), f"{current_number}"
        )
        current_number += 1
        self.assertEqual(CreditCardOrderCustomization.next_credit_card_order_number(self.user), f"{current_number}")
        # Enabled and using year
        CreditCardOrderCustomization.set("credit_card_order_number_template_enabled", "enabled")
        CreditCardOrderCustomization.set("credit_card_order_number_template_year", "2024")
        CreditCardOrderCustomization.set("credit_card_order_number_template", "{{ current_number }}")
        # Year but no user
        # We are using the year, so it's a different count
        current_number_year = 1
        self.assertEqual(
            CreditCardOrderCustomization.next_credit_card_order_number(self.user), f"{current_number_year}"
        )
        CreditCardOrderCustomization.set("credit_card_order_number_template", "{{ current_year }}-{{ current_number }}")
        self.assertEqual(
            CreditCardOrderCustomization.next_credit_card_order_number(self.user, save=True),
            f"2024-{current_number_year}",
        )
        current_number_year += 1
        self.assertEqual(
            CreditCardOrderCustomization.next_credit_card_order_number(self.user), f"2024-{current_number_year}"
        )
        # User but no year
        # Let's now use the user, so it's a different count
        current_number_user = 1
        CreditCardOrderCustomization.set("credit_card_order_number_template_year", "")
        CreditCardOrderCustomization.set("credit_card_order_number_template_user", "enabled")
        CreditCardOrderCustomization.set("credit_card_order_number_template", "{{ current_number }}")
        self.assertEqual(
            CreditCardOrderCustomization.next_credit_card_order_number(self.user, save=True), f"{current_number_user}"
        )
        current_number_user += 1
        CreditCardOrderCustomization.set(
            "credit_card_order_number_template", "{{ current_year }}-{{ user.username }}-{{ current_number }}"
        )
        self.assertEqual(
            CreditCardOrderCustomization.next_credit_card_order_number(self.user, save=True),
            f"-{self.user.username}-{current_number_user}",
        )
        # User and year
        # Let's now use both, so it's a different count again
        current_number_user_year = 1
        CreditCardOrderCustomization.set("credit_card_order_number_template_year", "24")
        CreditCardOrderCustomization.set("credit_card_order_number_template_user", "enabled")
        CreditCardOrderCustomization.set("credit_card_order_number_template", "{{ current_number }}")
        self.assertEqual(
            CreditCardOrderCustomization.next_credit_card_order_number(self.user, save=True),
            f"{current_number_user_year}",
        )
        current_number_user_year += 1
        CreditCardOrderCustomization.set(
            "credit_card_order_number_template", "{{ current_year }}-{{ user.username }}-{{ current_number }}"
        )
        self.assertEqual(
            CreditCardOrderCustomization.next_credit_card_order_number(self.user, save=True),
            f"24-{self.user.username}-{current_number_user_year}",
        )
        current_number_user_year += 1
        # Test with full numbering template: {year}-680-{FirstNameFirstLetter}{LastNameFirstLetter}{number with leading zeros}
        CreditCardOrderCustomization.set(
            "credit_card_order_number_template",
            "{{ current_year }}-680-{{ user.first_name.0|capfirst }}{{ user.last_name.0|capfirst }}{{ current_number|stringformat:'03d' }}",
        )
        self.assertEqual(CreditCardOrderCustomization.next_credit_card_order_number(self.user), f"24-680-TM003")
