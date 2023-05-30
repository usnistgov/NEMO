from django.apps import AppConfig


class ContractsConfig(AppConfig):
    name = "NEMO.apps.contracts"

    def ready(self):
        """
        This code will be run when Django starts.
        """
        pass
