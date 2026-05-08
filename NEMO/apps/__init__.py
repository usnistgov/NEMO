import sys

from django.apps import AppConfig
from django.contrib.auth.decorators import login_required


def monkey_patch_json_field_for_oracle():
    try:
        import oracledb
        from django.db.backends.oracle.base import FormatStylePlaceholderCursor

        original_output_type_handler = FormatStylePlaceholderCursor._output_type_handler

        # _get_lob_value AttributeError: 'dict' object has no attribute '_impl'
        # Django's _output_type_handler already knows that oracledb 2.0+ returns
        # NCLOB IS JSON columns as Python dicts instead of LOB objects, and tries
        # to work around it with cursor.var(DB_TYPE_NCLOB). In newer oracledb thick
        # mode this is no longer sufficient — the dict still ends up in the LOB
        # variable buffer, causing _get_lob_value to raise AttributeError.
        # Returning DB_TYPE_LONG forces Oracle to send the data as a plain string,
        # bypassing _get_lob_value entirely.
        def patched_output_type_handler(cursor, name, defaultType, length, precision, scale):
            if defaultType == oracledb.DB_TYPE_NCLOB:
                return cursor.var(oracledb.DB_TYPE_LONG, arraysize=cursor.arraysize)
            return original_output_type_handler(cursor, name, defaultType, length, precision, scale)

        FormatStylePlaceholderCursor._output_type_handler = staticmethod(patched_output_type_handler)
    except ImportError:
        pass

    from django.db.models.fields.json import JSONField

    # Save the original method
    original_from_db_value = JSONField.from_db_value

    # Define a wrapper that checks the type first
    def patched_from_db_value(self, value, expression, connection):
        # If the driver already parsed it into a native Python type, just return it
        if isinstance(value, (dict, list)):
            return value

        # Otherwise, let Django handle it as usual (string/bytes parsing)
        return original_from_db_value(self, value, expression, connection)

    # Apply the patch
    JSONField.from_db_value = patched_from_db_value


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
        from NEMO.plugins import utils  # needed for checks

        monkey_patch_json_field_for_oracle()

        if "migrate" in sys.argv or "makemigrations" in sys.argv:
            return
        from django.apps import apps

        if apps.is_installed("django.contrib.admin"):
            init_admin_site()
        init_rates()
