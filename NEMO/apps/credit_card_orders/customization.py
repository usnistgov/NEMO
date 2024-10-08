from NEMO.decorators import customization
from NEMO.views.customization import CustomizationBase


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
        # "credit_card_order_number_template_enabled": "",
        # "credit_card_order_number_template": "",
    }
