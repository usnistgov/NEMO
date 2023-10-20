import sys

from django.apps import AppConfig
from django.contrib.auth.decorators import login_required


def init_admin_site():
    from NEMO.views.customization import ApplicationCustomization, ProjectsAccountsCustomization
    from NEMO.admin import ProjectAdmin
    from django.contrib import admin

    # customize the site
    site_title = ApplicationCustomization.get("site_title", raise_exception=False)
    admin.site.login = login_required(admin.site.login)
    admin.site.site_header = site_title
    admin.site.site_title = site_title
    admin.site.index_title = "Detailed administration"
    # update the short_description for project's application identifier here after initialization
    ProjectAdmin.get_application_identifier.short_description = ProjectsAccountsCustomization.get(
        "project_application_identifier_name", raise_exception=False
    )


def init_rates():
    from NEMO.rates import rate_class

    rate_class.load_rates()


class NEMOConfig(AppConfig):
    default_auto_field = "django.db.models.AutoField"
    name = "NEMO"

    def ready(self):
        if "migrate" in sys.argv or "makemigrations" in sys.argv:
            return
        from django.apps import apps

        if apps.is_installed("django.contrib.admin"):
            init_admin_site()
        init_rates()


default_app_config = "NEMO.NEMOConfig"
