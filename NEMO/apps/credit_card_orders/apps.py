from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class CreditCardOrdersConfig(AppConfig):
    name = "NEMO.apps.credit_card_orders"
    verbose_name = _("Credit card orders")

    def ready(self):
        """
        This code will be run when Django starts.
        """
        pass
