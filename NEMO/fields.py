from __future__ import annotations

from typing import List, Tuple

from django import forms
from django.contrib.admin.widgets import AutocompleteMixin
from django.contrib.auth.models import Group, Permission
from django.core import validators
from django.core.cache import cache
from django.core.exceptions import FieldError, ValidationError
from django.db import models
from django.db.models.signals import post_delete, post_save
from django.utils.translation import gettext_lazy as _

from NEMO.typing import QuerySetType
from NEMO.utilities import quiet_int, strtobool

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


# This widget can be used with ChoiceField as or with CharField (choices needs to be used in attrs)
class DatalistWidget(forms.TextInput):

    def __init__(self, attrs=None):
        if attrs is not None:
            attrs = attrs.copy()
            self.choices = attrs.pop("choices", [])
        super().__init__(attrs)

    def render(self, name, value, attrs=None, renderer=None):
        if attrs is None:
            attrs = {}
        attrs["list"] = f"{name}_datalist"
        options = self.choices
        datalist = f'<datalist id="{name}_datalist">'
        for option_value, option_label in options:
            datalist += f'<option value="{option_value}">{option_label}</option>'
        datalist += "</datalist>"
        return super().render(name, value, attrs, renderer) + datalist


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
            return self.separator.join(value)
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
            return self.separator.join(value)
        else:
            return value


class MultiEmailField(models.CharField):
    description = "A multi e-mail field stored as a configurable character separated string"

    def __init__(self, separator=DEFAULT_SEPARATOR, *args, **kwargs):
        self.email_validator = validators.EmailValidator(
            message=_("Enter a valid email address or a list separated by {}").format(separator)
        )
        self.separator = separator
        kwargs.setdefault("max_length", 2000)
        super().__init__(*args, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        # Only include kwarg if it's not the default
        if self.separator != DEFAULT_SEPARATOR:
            kwargs["separator"] = self.separator
        return name, path, args, kwargs

    def formfield(self, **kwargs):
        # We are forcing our form class and widget here, replacing potential overrides from kwargs
        return super().formfield(
            **{**kwargs, "form_class": MultiEmailFormField, "widget": MultiEmailWidget, "separator": self.separator}
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
        return self.separator.join(value)

    def to_python(self, value):
        if isinstance(value, list):
            return value
        if value is None:
            return []
        return [address.strip() for address in value.split(self.separator) if address]

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


class DynamicChoicesCharField(models.CharField):
    """
    Represents a dynamic choices character field for Django models.

    This will make sure migrations are not triggered when the choices are updated.
    """

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        kwargs.pop("choices", None)
        return name, path, args, kwargs


class DynamicChoicesIntegerField(models.IntegerField):
    """
    Represents a dynamic choices integer field for Django models.

    This will make sure migrations are not triggered when the choices are updated.
    """

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        kwargs.pop("choices", None)
        return name, path, args, kwargs


# Choice field for picking roles, groups or permissions
# Usage: role = RoleGroupPermissionChoiceField(roles=True/False, groups=True/False, permissions=True/False)
class RoleGroupPermissionChoiceField(DynamicChoicesCharField):
    GROUPS_CACHE_KEY = "group_choices"
    PERMISSIONS_CACHE_KEY = "permission_choices"

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
        super().__init__(*args, **kwargs)

    def role_choices(self) -> List[Tuple[str, str]]:
        role_choice_list = [(self.empty_value, self.empty_label)]

        if self.roles:
            role_choice_list.extend(
                [
                    ("is_staff", "Role: Staff"),
                    ("is_user_office", "Role: User Office"),
                    ("is_accounting_officer", "Role: Accounting officers"),
                    ("is_facility_manager", "Role: Facility managers"),
                    ("is_superuser", "Role: Administrators"),
                ]
            )

        if self.groups:
            group_choices = cache.get(self.GROUPS_CACHE_KEY)
            if group_choices is None:
                group_choices = [(str(group.id), f"Group: {group.name}") for group in Group.objects.all()]
                cache.set(self.GROUPS_CACHE_KEY, group_choices)
            role_choice_list.extend(group_choices)

        if self.permissions:
            permission_choices = cache.get(self.PERMISSIONS_CACHE_KEY)
            if permission_choices is None:
                permission_choices = [
                    (p["codename"], f'Permission: {p["name"]}') for p in Permission.objects.values("codename", "name")
                ]
                cache.set(self.PERMISSIONS_CACHE_KEY, permission_choices)
            role_choice_list.extend(permission_choices)

        return role_choice_list

    def has_user_role(self, role: str, user) -> bool:
        if not user.is_active:
            return False
        if self.roles:
            if hasattr(user, role):
                return getattr(user, role, False)
        if self.groups:
            # check that it's a number
            if quiet_int(role, None):
                group = Group.objects.filter(id=role).exists()
                if group:
                    return user.groups.filter(id=role).exists()
        if self.permissions:
            permission = Permission.objects.filter(codename__iexact=role).first()
            if permission:
                return user.has_perm(permission)
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
                    role_users = users.filter(**{role: True})
                except FieldError:
                    # we expect this if it's not a real role
                    pass
            if self.groups and role.isdigit():
                group_users = users.filter(groups__id__in=role)
            if self.permissions:
                permission_users = users.filter(
                    models.Q(user_permissions__codename__iexact=role) | models.Q(is_superuser=True)
                )
            return role_users | group_users | permission_users
        return User.objects.none()

    def role_display(self, role: str) -> str:
        for key, value in self.role_choices():
            if key == role:
                return value
        return ""

    def formfield(self, **kwargs):
        self.choices = kwargs.pop("choices", self.role_choices())
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


RoleGroupPermissionChoiceField.connect_signals()
