from distutils.util import strtobool

from django import forms
from django.core import validators
from django.core.exceptions import ValidationError
from django.core.validators import EmailValidator
from django.db import models
from django.db.models import Field
from django.db.models.lookups import BuiltinLookup
from django.utils.translation import gettext_lazy as _

DEFAULT_SEPARATOR = ","


@Field.register_lookup
class IsEmpty(BuiltinLookup):
	# Custom lookup allowing to use __isempty in filters and REST API
	lookup_name = "isempty"
	prepare_rhs = False

	def as_sql(self, compiler, connection):
		sql, params = compiler.compile(self.lhs)
		condition = self.rhs if isinstance(self.rhs, bool) else bool(strtobool(self.rhs))
		if condition:
			return "%s IS NULL or %s = ''" % (sql, sql), params
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
		if value is None:
			return value
		return self.separator.join(value)


class MultiEmailField(models.CharField):
	description = "A multi e-mail field stored as a configurable character separated string"

	def __init__(self, separator=DEFAULT_SEPARATOR, *args, **kwargs):
		self.email_validator = EmailValidator(
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
		return [address.strip() for address in value.split(self.separator)]

	def value_to_string(self, obj):
		value = self.value_from_object(obj)
		return self.get_prep_value(value)
