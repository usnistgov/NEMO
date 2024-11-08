from django.apps import AppConfig


class AreaAccessConfig(AppConfig):
    name = "NEMO.apps.area_access"

    def ready(self):
        """
        This code will be run when Django starts.
        """
        pass
