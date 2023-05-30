from django.core.validators import validate_comma_separated_integer_list

from NEMO.decorators import customization
from NEMO.views.customization import CustomizationBase


@customization(title="Contracts & Procurements", key="contracts")
class ContractsCustomization(CustomizationBase):
    variables = {
        "contracts_view_staff": "",
        "contracts_view_user_office": "",
        "contracts_view_accounting_officer": "",
        "contracts_contractors_default_empty_label": "Credit card order",
        "contracts_renewal_reminder_days": "",
        "contracts_contractors_reminder_days": "",
    }

    def validate(self, name, value):
        if name in ["contracts_renewal_reminder_days", "contracts_contractors_reminder_days"] and value:
            # Check that we have an integer or a list of integers
            validate_comma_separated_integer_list(value)
