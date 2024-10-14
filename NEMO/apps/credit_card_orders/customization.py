from __future__ import annotations

from logging import getLogger
from typing import Dict, TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.db.models import Q
from django.template import Context, Template

from NEMO.decorators import customization
from NEMO.models import Customization, User
from NEMO.utilities import quiet_int
from NEMO.views.customization import CustomizationBase

if TYPE_CHECKING:
    from NEMO.apps.credit_card_orders.models import CreditCardOrder

cc_customization_logger = getLogger(__name__)


@customization(title="Credit card orders", key="credit_card_orders")
class CreditCardOrderCustomization(CustomizationBase):
    variables = {
        "credit_card_order_view_staff": "",
        "credit_card_order_view_user_office": "",
        "credit_card_order_view_accounting_officer": "",
        "credit_card_order_create_staff": "",
        "credit_card_order_create_user_office": "",
        "credit_card_order_create_accounting_officer": "",
        "credit_card_order_self_approval_allowed": "",
        "credit_card_order_number_template_enabled": "",
        "credit_card_order_number_template_year": "",
        "credit_card_order_number_template_user": "",
        "credit_card_order_number_template": "",
    }

    def context(self) -> Dict:
        dictionary = super().context()
        # if we have a year set then we reset the numbering per year
        current_number = "credit_card_order_current_number"
        order_number_template_current_year = dictionary["credit_card_order_number_template_year"]
        order_number_by_user = dictionary["credit_card_order_number_template_user"]
        if order_number_template_current_year:
            current_number += f"_{order_number_template_current_year}"
        current_number_filter = (
            Q(name__startswith=current_number + "_") if order_number_by_user else Q(name=current_number)
        )
        dictionary["current_numbers"] = {
            current_order_number_per_user.name: current_order_number_per_user.value
            for current_order_number_per_user in Customization.objects.filter(current_number_filter)
        }
        return dictionary

    def validate(self, name, value):
        if name == "credit_card_order_number_template" and value:
            try:
                fake_user = User(first_name="Testy", last_name="McTester", email="testy_mctester@gmail.com")
                self.next_credit_card_order_number(fake_user, save=False)
            except Exception as e:
                raise ValidationError(str(e))

    @classmethod
    def next_credit_card_order_number(cls, user: User, credit_card_order: CreditCardOrder = None, save=False) -> str:
        if CreditCardOrderCustomization.get_bool("credit_card_order_number_template_enabled"):
            order_number_template_current_year = CreditCardOrderCustomization.get_int(
                "credit_card_order_number_template_year"
            )
            order_number_template = CreditCardOrderCustomization.get("credit_card_order_number_template")
            order_number_by_user = CreditCardOrderCustomization.get_bool("credit_card_order_number_template_user")
            current_number_customization = "credit_card_order_current_number"
            if order_number_template_current_year:
                current_number_customization += f"_{order_number_template_current_year}"
            if order_number_by_user:
                current_number_customization += f"_{user.username}"
            current_number = Customization.objects.filter(name=current_number_customization).first()
            current_number_value = quiet_int(current_number.value, 1) if current_number else 1
            context = {
                "credit_card_order": credit_card_order,
                "user": user,
                "current_year": order_number_template_current_year or "",
                "current_number": current_number_value,
            }
            if save:
                try:
                    Customization(name=current_number_customization, value=current_number_value + 1).save()
                except:
                    cc_customization_logger.exception("Error saving credit card order current number")
            order_number = Template(order_number_template).render(Context(context))
            return order_number
