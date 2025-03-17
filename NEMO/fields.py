from __future__ import annotations

from typing import List, Tuple

from django import forms
from django.contrib.admin.widgets import AutocompleteMixin, FilteredSelectMultiple
from django.contrib.auth.models import Group, Permission
from django.core import validators
from django.core.cache import cache
from django.core.exceptions import FieldError, ValidationError
from django.db import connection, models
from django.db.models.signals import post_delete, post_save
from django.utils.translation import gettext_lazy as _

from NEMO.typing import QuerySetType
from NEMO.utilities import CommaSeparatedListConverter, DelimiterSeparatedListConverter, quiet_int, strtobool

DEFAULT_SEPARATOR = ","


@models.Field.register_lookup
class IsEmpty(models.lookups.BuiltinLookup):
    # Custom lookup allowing to use __isempty in filters and REST API
    lookup_name = "isempty"
    prepare_rhs = False

    def as_sql(self, compiler, connection):
        sql, params = compiler.compile(self.lhs)
        condition = self.rhs if isinstance(self.rhs, bool) else bool(strtobool(self.rhs))
        if condition:
            return "%s IS NULL or %s = ''" % (sql, sql), params
        else:
            if getattr(connection, "vendor", "") == "oracle" and isinstance(self.lhs.field, models.TextField):
                # we need to handle textfields for oracle differently as they are set as clobs
                return "length(%s) <> 0" % sql, params
            else:
                return "%s <> ''" % sql, params


class MultiEmailWidget(forms.TextInput):
    is_hidden = False
    separator = DEFAULT_SEPARATOR

    def __init__(self, attrs=None):
        super().__init__(attrs={"size": "129", **(attrs or {})})

    def prep_value(self, value):
        if self.attrs and "separator" in self.attrs:
            self.separator = self.attrs.pop("separator")

        if value in validators.EMPTY_VALUES + ("[]",):
            return ""
        elif isinstance(value, str):
            return value
        elif isinstance(value, list):
            return DelimiterSeparatedListConverter(self.separator).to_string(value)
        raise ValidationError("Invalid format.")

    def render(self, name, value, **kwargs):
        value = self.prep_value(value)
        return super().render(name, value, **kwargs)


class MultiEmailFormField(forms.CharField):
    widget = MultiEmailWidget

    def __init__(self, separator=DEFAULT_SEPARATOR, **kwargs):
        self.separator = separator
        super().__init__(**kwargs)

    def widget_attrs(self, widget):
        attrs = super().widget_attrs(widget)
        attrs["separator"] = self.separator
        return attrs

    def prepare_value(self, value):
        if type(value) is list:
            return DelimiterSeparatedListConverter(self.separator).to_string(value)
        else:
            return value


class MultiEmailField(models.CharField):
    description = "A multi e-mail field stored as a configurable character separated string"

    def __init__(self, separator=DEFAULT_SEPARATOR, *args, **kwargs):
        self.email_validator = validators.EmailValidator(
            message=_("Enter a valid email address or a list separated by {}").format(separator)
        )
        self.separator = separator
        self.delimiter_separated_list = DelimiterSeparatedListConverter(self.separator)
        kwargs.setdefault("max_length", 2000)
        self.widget = kwargs.pop("widget", MultiEmailWidget())
        super().__init__(*args, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        # Only include kwarg if it's not the default
        if self.separator != DEFAULT_SEPARATOR:
            kwargs["separator"] = self.separator
        return name, path, args, kwargs

    def formfield(self, **kwargs):
        # We are forcing our form class and widget here, replacing potential overrides from kwargs.
        # It can still be overridden in the field declaration.
        return super().formfield(
            **{**kwargs, "form_class": MultiEmailFormField, "widget": self.widget, "separator": self.separator}
        )

    def validate(self, value, model_instance):
        """Check if value consists only of valid emails."""
        super().validate(self.get_prep_value(value), model_instance)
        for email in value:
            self.email_validator(email.strip())

    def from_db_value(self, value, expression, connection):
        return self.to_python(value)

    def get_prep_value(self, value):
        if value is None:
            return value
        return self.delimiter_separated_list.to_string(value)

    def to_python(self, value):
        return self.delimiter_separated_list.to_list(value)

    def value_to_string(self, obj):
        value = self.value_from_object(obj)
        return self.get_prep_value(value)


# Django admin special widget to allow select2 autocomplete for choice fields
class AdminAutocompleteSelectWidget(forms.Select):
    def __init__(self, choices=(), attrs=None):
        super().__init__(attrs)
        self.choices = choices

    def render(self, name, value, attrs=None, renderer=None):
        select_html = super().render(name, value, attrs, renderer)
        select2_script = f"""
        <script type="text/javascript">
            (function($) {{
                $(document).ready(function() {{
                    $('#id_{name}').select2();
                }});
            }})(django.jQuery);
        </script>
        """
        return select_html + select2_script

    @property
    def media(self):
        # Reuse the AutocompleteMixin's media files
        return AutocompleteMixin(None, None).media


class CommaSeparatedTextMultipleChoiceField(forms.MultipleChoiceField):
    """
    Custom form field for multiple choice options represented as a comma-separated
    text string.

    This class extends `forms.MultipleChoiceField` to handle input where multiple
    choices are provided as a single string of values separated by commas.
    It converts the input value into a list of choices for processing.
    """

    def prepare_value(self, value) -> List:
        return CommaSeparatedListConverter.to_list(value)


class DynamicChoicesMixin:
    """
    Mixin class to handle dynamic choices for a field.

    This class allows choices to be dynamically modified or excluded during
    serialization such as migration serialization. It provides utility for
    fields that require dynamic handling of their choices attribute. This can
    help prevent hardcoding choices into migrations.
    """

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        kwargs.pop("choices", None)
        return name, path, args, kwargs


class DynamicChoicesIntegerField(DynamicChoicesMixin, models.IntegerField):
    """
    IntegerField with support for dynamic choices.
    """

    pass


class DynamicChoicesCharField(DynamicChoicesMixin, models.CharField):
    """
    CharField with support for dynamic choices.
    """

    pass


class DynamicChoicesTextField(DynamicChoicesMixin, models.TextField):
    """
    TextField with support for dynamic choices.
    """

    pass


# Choice field for picking roles, groups or permissions
# Usage: role = RoleGroupPermissionChoiceField(roles=True/False, groups=True/False, permissions=True/False)
class RoleGroupPermissionChoiceField(DynamicChoicesTextField):
    class Role(models.TextChoices):
        IS_AUTHENTICATED = "is_authenticated", _("Anyone")
        NON_STAFF_USERS = "non_staff_users", _("Non-staff users")
        IS_STAFF = "is_staff", _("Staff")
        IS_USER_OFFICE = "is_user_office", _("User Office")
        IS_ACCOUNTING_OFFICER = "is_accounting_officer", _("Accounting officers")
        IS_SERVICE_PERSONNEL = "is_service_personnel", _("Service Personnel")
        IS_TECHNICIAN = "is_technician", _("Technician")
        IS_FACILITY_MANAGER = "is_facility_manager", _("Facility managers")
        IS_SUPERUSER = "is_superuser", _("Administrators")

    NON_STAFF_USER_EXCLUDE_FILTER = (
        models.Q(is_staff=True)
        | models.Q(is_accounting_officer=True)
        | models.Q(is_user_office=True)
        | models.Q(is_facility_manager=True)
        | models.Q(is_superuser=True)
    )

    GROUPS_CACHE_KEY = "group_choices"
    PERMISSIONS_CACHE_KEY = "permission_choices"

    PREFIX_ROLE_DISPLAY = _("Role: ")
    PREFIX_GROUP_DISPLAY = _("Group: ")
    PREFIX_PERMISSION_DISPLAY = _("Permission: ")

    def __init__(
        self,
        *args,
        roles=True,
        groups=False,
        permissions=False,
        empty_value=models.fields.BLANK_CHOICE_DASH[0][0],
        empty_label=models.fields.BLANK_CHOICE_DASH[0][1],
        **kwargs,
    ):
        self.roles = roles
        self.groups = groups
        self.permissions = permissions
        self.empty_label = empty_label
        self.empty_value = empty_value
        if not any([roles, groups, permissions]):
            raise ValueError("At least one of roles, groups or permissions must be selected.")
        super().__init__(*args, **kwargs)

    def role_choices(self, admin_display=False, include_blank=True) -> List[Tuple[str, str]]:
        role_choice_list = [(self.empty_value, self.empty_label)] if include_blank else []

        if self.roles:
            prefix = self.PREFIX_ROLE_DISPLAY if admin_display else ""
            for role_choice in self.Role.choices:
                role_choice_list.append((role_choice[0], prefix + role_choice[1]))

        if self.groups and "auth_group" in connection.introspection.table_names():
            group_choices = cache.get(self.GROUPS_CACHE_KEY)
            prefix = self.PREFIX_GROUP_DISPLAY if admin_display else ""
            if group_choices is None:
                group_choices = [(str(group.id), group.name) for group in Group.objects.all()]
                cache.set(self.GROUPS_CACHE_KEY, group_choices)
            role_choice_list.extend([(group_choice[0], prefix + group_choice[1]) for group_choice in group_choices])

        if self.permissions and "auth_permission" in connection.introspection.table_names():
            permission_choices = cache.get(self.PERMISSIONS_CACHE_KEY)
            prefix = self.PREFIX_PERMISSION_DISPLAY if admin_display else ""
            if permission_choices is None:
                permission_choices = [
                    (f'{p["content_type__app_label"]}.{p["codename"]}', p["name"])
                    for p in Permission.objects.values("content_type__app_label", "codename", "name")
                ]
                cache.set(self.PERMISSIONS_CACHE_KEY, permission_choices)
            role_choice_list.extend([(perm_choice[0], prefix + perm_choice[1]) for perm_choice in permission_choices])

        return role_choice_list

    def has_user_role(self, role: str, user) -> bool:
        from NEMO.models import User

        if not user.is_active:
            return False
        if self.roles:
            if hasattr(user, role):
                return getattr(user, role, False)
            elif role == self.Role.NON_STAFF_USERS:
                return User.objects.filter(pk=user.pk).exclude(self.NON_STAFF_USER_EXCLUDE_FILTER).exists()
        if self.groups:
            # check that it's a number
            if quiet_int(role, None):
                group = Group.objects.filter(id=role).exists()
                if group:
                    return user.groups.filter(id=role).exists()
        if self.permissions:
            app_label, _, codename = role.partition(".")
            if app_label and codename:
                permission = Permission.objects.filter(
                    content_type__app_label=app_label, codename__iexact=codename
                ).first()
                if permission:
                    return user.has_perm(role)
        return False

    def users_with_role(self, role: str) -> QuerySetType:
        from NEMO.models import User

        users = User.objects.filter(is_active=True)
        if role:
            role_users = User.objects.none()
            group_users = User.objects.none()
            permission_users = User.objects.none()
            if self.roles:
                try:
                    if role == self.Role.NON_STAFF_USERS:
                        role_users = users.exclude(self.NON_STAFF_USER_EXCLUDE_FILTER)
                    else:
                        role_users = users.filter(**{role: True})
                except FieldError:
                    # we expect this if it's not a real role
                    pass
            if self.groups and role.isdigit():
                group_users = users.filter(groups__id__in=role)
            if self.permissions:
                app_label, _, codename = role.partition(".")
                if app_label and codename:
                    permission_users = users.filter(
                        models.Q(
                            user_permissions__codename__iexact=codename,
                            user_permissions__content_type__app_label=app_label,
                        )
                        | models.Q(is_superuser=True)
                    )
            return role_users | group_users | permission_users
        return User.objects.none()

    def role_display(self, role: str, admin_display=False) -> str:
        for key, value in self.role_choices(admin_display=admin_display):
            if key == role:
                return value
        return ""

    def formfield(self, **kwargs):
        self.choices = kwargs.pop("choices", self.role_choices(admin_display=True))
        submitted_widget = kwargs.pop("widget", AdminAutocompleteSelectWidget(attrs={"style": "width: 400px;"}))
        empty_label = kwargs.pop("empty_label", self.empty_label)
        empty_value = kwargs.pop("empty_value", self.empty_value)
        return super().formfield(widget=submitted_widget, empty_label=empty_label, empty_value=empty_value, **kwargs)

    # Signal handlers for cache invalidation
    @staticmethod
    def invalidate_group_cache(sender, **kwargs):
        cache.delete(RoleGroupPermissionChoiceField.GROUPS_CACHE_KEY)

    @staticmethod
    def invalidate_permission_cache(sender, **kwargs):
        cache.delete(RoleGroupPermissionChoiceField.PERMISSIONS_CACHE_KEY)

    # Connect the invalidation signals
    @classmethod
    def connect_signals(cls):
        post_save.connect(cls.invalidate_group_cache, sender=Group)
        post_delete.connect(cls.invalidate_group_cache, sender=Group)
        post_save.connect(cls.invalidate_permission_cache, sender=Permission)
        post_delete.connect(cls.invalidate_permission_cache, sender=Permission)


class MultiRoleGroupPermissionChoiceField(RoleGroupPermissionChoiceField):
    """
    A specialized field that extends RoleGroupPermissionChoiceField for handling multiple role permissions.

    This class adds functionality for handling multiple roles, including displaying roles in a readable format,
    converting them for storage or form usage, and verifying user role permissions.
    """

    def formfield(self, **kwargs):
        choices = kwargs.pop("choices", self.role_choices(admin_display=True, include_blank=False))
        is_stacked = kwargs.pop("is_stacked", False)
        kwargs["widget"] = FilteredSelectMultiple("Roles", is_stacked=is_stacked)
        return super(models.TextField, self).formfield(
            choices=choices, form_class=CommaSeparatedTextMultipleChoiceField, **kwargs
        )

    def to_python(self, value) -> List:
        return CommaSeparatedListConverter.to_list(value)

    def from_db_value(self, value, *args, **kwargs) -> List:
        return self.to_python(value)

    def get_prep_value(self, value) -> str:
        return CommaSeparatedListConverter.to_string(value)

    def has_user_roles(self, roles: List[str], user):
        """
        Override to check a list of roles instead of a single one.
        """
        if not user.is_active:
            return False

        return any(self.has_user_role(role, user) for role in roles)

    def roles_display(self, roles: List[str], admin_display=True) -> str:
        """
        Convert the list of selected roles to a string for display purposes.
        """
        return ", ".join(self.role_display(role, admin_display=admin_display) for role in roles)

    def get_choices(self, *args, **kwargs):
        kwargs["include_blank"] = False
        return super().get_choices(*args, **kwargs)


RoleGroupPermissionChoiceField.connect_signals()
