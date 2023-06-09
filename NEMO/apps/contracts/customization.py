from NEMO.decorators import customization
from NEMO.views.customization import CustomizationBase


@customization(title="Contracts & Procurements", key="contracts")
class ContractsCustomization(CustomizationBase):
    variables = {
        "contracts_view_staff": "",
        "contracts_view_user_office": "",
        "contracts_view_accounting_officer": "",
        "contracts_contractors_default_empty_label": "Credit card order",
    }
