from django.apps import AppConfig


class SensorsConfig(AppConfig):
    name = "NEMO.apps.sensors"
    label = "sensors"

    def ready(self):
        """
        This code will be run when Django starts.
        """
        pass
