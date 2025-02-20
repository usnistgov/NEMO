from django.apps import AppConfig


class KioskConfig(AppConfig):
    name = "NEMO.apps.kiosk"

    def ready(self):
        """
        This code will be run when Django starts.
        """
        pass
