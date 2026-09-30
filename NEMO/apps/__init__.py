import sys
import warnings

from django.apps import AppConfig
from django.contrib.auth.decorators import login_required


def apply_oracledb_patches():
    """
    Compatibility patches for oracledb 2.0+ thick mode with newer Oracle databases.

    In oracledb 2.0+ thick mode, NCLOB columns with an IS JSON constraint are
    returned as Python dicts instead of LOB objects. Django's own cursor output
    type handler tries to prevent this with cursor.var(DB_TYPE_NCLOB), but in
    newer oracledb versions that no longer stops the dict from ending up in the
    LOB variable buffer, causing _get_lob_value to raise AttributeError.

    Patch 1 overrides Django's handler to return NCLOB as DB_TYPE_LONG (plain
    string), bypassing the LOB path entirely.
    Patch 2 is a safety net for any JSON column oracledb returns as a native
    Python type before Django's JSONField.from_db_value can process it.
    """
    try:
        import oracledb
        from django.db.backends.oracle.base import FormatStylePlaceholderCursor
    except:
        return

    original_output_type_handler = FormatStylePlaceholderCursor._output_type_handler

    def patched_output_type_handler(cursor, name, defaultType, length, precision, scale):
        if defaultType == oracledb.DB_TYPE_NCLOB:
            return cursor.var(oracledb.DB_TYPE_LONG, arraysize=cursor.arraysize)
        return original_output_type_handler(cursor, name, defaultType, length, precision, scale)

    FormatStylePlaceholderCursor._output_type_handler = staticmethod(patched_output_type_handler)

    from django.db.models.fields.json import JSONField

    original_from_db_value = JSONField.from_db_value

    def patched_from_db_value(self, value, expression, connection):
        if isinstance(value, (dict, list)):
            return value
        return original_from_db_value(self, value, expression, connection)

    JSONField.from_db_value = patched_from_db_value


def init_admin_site():
    from NEMO.views.customization import (
        ApplicationCustomization,
        ProjectsAccountsCustomization,
        CoreFacilityCustomization,
    )
    from NEMO.admin import ProjectAdmin, CoreFacilityAdmin
    from django.contrib import admin

    # customize the site
    site_title = ApplicationCustomization.get("site_title", raise_exception=False)
    admin.site.login = login_required(admin.site.login)
    admin.site.site_header = site_title
    admin.site.site_title = site_title
    admin.site.index_title = "Detailed administration"
    # update the short_description for project's application identifier and core facility's external identifier here after initialization
    ProjectAdmin.get_application_identifier.short_description = ProjectsAccountsCustomization.get(
        "project_application_identifier_name", raise_exception=False
    )
    CoreFacilityAdmin.get_external_id.short_description = CoreFacilityCustomization.get(
        "core_facility_external_id_name", raise_exception=False
    )


def init_rates():
    from NEMO.rates import rate_class

    rate_class.load_rates()


class NEMOConfig(AppConfig):
    default_auto_field = "django.db.models.AutoField"
    name = "NEMO"

    def ready(self):
        from NEMO.plugins import utils  # needed for checks

        apply_oracledb_patches()

        if "migrate" in sys.argv or "makemigrations" in sys.argv:
            return
        from django.apps import apps

        # ignore warning when initializing admin site and rates
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=RuntimeWarning)

            if apps.is_installed("django.contrib.admin"):
                init_admin_site()
            init_rates()
