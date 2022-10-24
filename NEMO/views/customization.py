import operator
from abc import ABC
from typing import Dict, Iterable

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.files.storage import get_storage_class
from django.core.validators import validate_email
from django.http import HttpResponseNotFound
from django.shortcuts import redirect, render
from django.template import Context, Template
from django.views.decorators.http import require_GET, require_POST

from NEMO import init_admin_site
from NEMO.decorators import administrator_required, customization
from NEMO.exceptions import InvalidCustomizationException
from NEMO.models import Customization, Project


class CustomizationBase(ABC):
	_instances = {}
	# Here we can place variables that we need in NEMO but don't need to be set in UI
	variables = {"weekend_access_notification_last_sent": ""}
	files = []

	def __init__(self, key, title, order):
		self.key = key
		self.title = title
		self.order = order

	def template(self) -> str:
		return f"customizations/customizations_{self.key}.html"

	def context(self) -> Dict:
		files_dict = {name: get_media_file_contents(name + extension) for name, extension in type(self).files}
		variables_dict = {name: type(self).get(name) for name in type(self).variables}
		return {"customization": self, **variables_dict, **files_dict}

	def save(self, request, element=None) -> Dict[str, Dict[str, str]]:
		errors = {}
		if element:
			# We are saving a file here
			item = None
			for name, extension in type(self).files:
				if name == element:
					item = (name, extension)
					break
			if item:
				store_media_file(request.FILES.get(element, ""), item[0] + item[1])
		else:
			# We are saving key values here
			for key in type(self).variables.keys():
				new_value = request.POST.get(key, "")
				try:
					self.validate(key, new_value)
					type(self).set(key, new_value)
				except (ValidationError, InvalidCustomizationException) as e:
					errors[key] = {"error": str(e.message or e.msg), "value": new_value}
		return errors

	def validate(self, name, value):
		# This method is expected to throw a ValidationError when validation fails
		pass

	@classmethod
	def add_instance(cls, inst):
		cls._instances[inst.key] = inst

	@classmethod
	def instances(cls) -> Iterable:
		return sorted(cls._instances.values(), key=operator.attrgetter("order"))

	@classmethod
	def get_instance(cls, key):
		return cls._instances.get(key)

	@classmethod
	def all_variables(cls) -> Dict:
		all_variables = CustomizationBase.variables
		for instance in cls.instances():
			all_variables.update(instance.variables)
		return all_variables

	@classmethod
	def get(cls, name: str, raise_exception=True) -> str:
		if name not in cls.variables:
			raise InvalidCustomizationException(name)
		default_value = cls.variables[name]
		try:
			return Customization.objects.get(name=name).value
		except Customization.DoesNotExist:
			# return default value
			return default_value
		except Exception:
			if raise_exception:
				raise
			else:
				return default_value

	@classmethod
	def set(cls, name: str, value):
		if name not in cls.variables:
			raise InvalidCustomizationException(name, value)
		if value:
			Customization.objects.update_or_create(name=name, defaults={"value": value})
		else:
			try:
				Customization.objects.get(name=name).delete()
			except Customization.DoesNotExist:
				pass


@customization(key="application", title="Application", order=1)
class ApplicationCustomization(CustomizationBase):
	variables = {
		"facility_name": "Facility",
		"site_title": "NEMO",
		"self_log_in": "",
		"self_log_out": "",
		"calendar_login_logout": "",
		"project_selection_template": "{{ project.name }}",
	}

	def validate(self, name, value):
		if name == "project_selection_template":
			try:
				Template(value).render(Context({"project": Project()}))
			except Exception as e:
				raise ValidationError(str(e))

	def save(self, request, element=None):
		errors = super().save(request, element)
		init_admin_site()
		return errors


@customization(key="user", title="User", order=2)
class UserCustomization(CustomizationBase):
	variables = {
		"default_user_training_not_required": "",
		"user_list_active_only": "",
		"user_access_expiration_reminder_days": "",
		"user_access_expiration_reminder_cc": "",
		"user_tool_qualification_reminder_days": "",
		"user_tool_qualification_expiration_days": "",
		"user_tool_qualification_expiration_never_used_days": "",
		"user_tool_qualification_cc": "",
	}

	def validate(self, name, value):
		if name == "user_tool_qualification_expiration_days" and value:
			try:
				int(value)
			except ValueError:
				raise ValidationError(f"{value} is not a valid integer")
		if name in ["user_access_expiration_reminder_days", "user_tool_qualification_reminder_days"] and value:
			# Check that we have an integer or a list of integers
			try:
				for reminder_days in value.split(","):
					try:
						int(reminder_days)
					except ValueError:
						raise ValidationError(f"{reminder_days} is not a valid integer")
			except ValidationError:
				raise
			except Exception as e:
				raise ValidationError(str(e))
		elif name in ["user_access_expiration_reminder_cc", "user_tool_qualification_cc"]:
			recipients = tuple([e for e in value.split(",") if e])
			for email in recipients:
				validate_email(email)


@customization(key="emails", title="Email addresses", order=2)
class EmailsCustomization(CustomizationBase):
	variables = {
		"feedback_email_address": "",
		"user_office_email_address": "",
		"safety_email_address": "",
		"abuse_email_address": "",
	}

	def validate(self, name, value):
		validate_email(value)


@customization(key="calendar", title="Calendar", order=3)
class CalendarCustomization(CustomizationBase):
	variables = {
		"calendar_view": "agendaWeek",
		"calendar_first_day_of_week": "1",
		"calendar_day_column_format": "dddd MM/DD/YYYY",
		"calendar_week_column_format": "ddd M/DD",
		"calendar_month_column_format": "ddd",
		"calendar_start_of_the_day": "07:00:00",
		"calendar_now_indicator": "",
		"calendar_display_not_qualified_areas": "",
		"calendar_all_tools": "",
		"calendar_all_areas": "",
		"calendar_all_areastools": "",
		"calendar_outage_recurrence_limit": "90",
		"calendar_qualified_tools": ""
	}


@customization(key="dashboard", title="Status dashboard", order=4)
class StatusDashboardCustomization(CustomizationBase):
	variables = {
		"dashboard_display_not_qualified_areas": "",
		"dashboard_staff_status_first_day_of_week": "1",
		"dashboard_staff_status_staff_only": "",
		"dashboard_staff_status_weekdays_only": "",
		"dashboard_staff_status_date_format": "D m/d",
		"dashboard_staff_status_check_past_status": "",
		"dashboard_staff_status_check_future_status": "",
		"dashboard_staff_status_user_view": "",
		"dashboard_staff_status_staff_view": "",
	}


@customization(key="interlock", title="Interlock", order=5)
class InterlockCustomization(CustomizationBase):
	variables = {
		"allow_bypass_interlock_on_failure": "",
		"tool_interlock_failure_message": "Communication with the interlock failed",
		"door_interlock_failure_message": "Communication with the interlock failed",
	}


@customization(key="requests", title="User requests", order=6)
class UserRequestsCustomization(CustomizationBase):
	variables = {
		"buddy_requests_title": "Buddy requests board",
		"buddy_board_description": "",
		"access_requests_title": "Access requests",
		"access_requests_description": "",
		"access_requests_minimum_users": "2",
		"access_requests_display_max": "",
		"weekend_access_notification_emails": "",
		"weekend_access_notification_cutoff_hour": "",
		"weekend_access_notification_cutoff_day": "",
	}

	def validate(self, name, value):
		if name == "weekend_access_notification_emails":
			recipients = tuple([e for e in value.split(",") if e])
			for email in recipients:
				validate_email(email)


@customization(key="templates", title="File & email templates", order=7)
class TemplatesCustomization(CustomizationBase):
	files = [
		("login_banner", ".html"),
		("authorization_failed", ".html"),
		("safety_introduction", ".html"),
		("facility_rules_tutorial", ".html"),
		("jumbotron_watermark", ".png"),
		("access_request_notification_email", ".html"),
		("cancellation_email", ".html"),
		("counter_threshold_reached_email", ".html"),
		("feedback_email", ".html"),
		("generic_email", ".html"),
		("missed_reservation_email", ".html"),
		("facility_rules_tutorial_email", ".html"),
		("new_task_email", ".html"),
		("out_of_time_reservation_email", ".html"),
		("reorder_supplies_reminder_email", ".html"),
		("reservation_ending_reminder_email", ".html"),
		("reservation_reminder_email", ".html"),
		("reservation_warning_email", ".html"),
		("safety_issue_email", ".html"),
		("staff_charge_reminder_email", ".html"),
		("task_status_notification", ".html"),
		("tool_qualification_expiration_email", ".html"),
		("unauthorized_tool_access_email", ".html"),
		("usage_reminder_email", ".html"),
		("user_access_expiration_reminder_email", ".html"),
		("reservation_created_user_email", ".html"),
		("reservation_cancelled_user_email", ".html"),
		("weekend_access_email", ".html"),
	]


@customization(key="rates", title="Rates", order=8)
class RatesCustomization(CustomizationBase):
	variables = {"rates_expand_table": ""}
	files = [("rates", ".json")]

	def save(self, request, element=None):
		errors = super().save(request, element)
		if not errors:
			from NEMO.rates import rate_class

			rate_class.load_rates(force_reload=True)
		return errors


def get_media_file_contents(file_name):
	""" Get the contents of a media file if it exists. Return a blank string if it does not exist. """
	storage = get_storage_class()()
	if not storage.exists(file_name):
		return ""
	with storage.open(file_name) as opened_file:
		read_file = opened_file.read()
		try:
			return read_file.decode().strip()
		except UnicodeDecodeError:
			return read_file


def store_media_file(content, file_name):
	""" Delete any existing media file with the same name and save the new content into file_name in the media directory. If content is blank then no new file is created. """
	storage = get_storage_class()()
	storage.delete(file_name)
	if content:
		storage.save(file_name, content)


# This method should not be used anymore. Instead, use XCustomization.get(name)
def get_customization(name, raise_exception=True):
	customizable_key_values = CustomizationBase.all_variables()
	if name not in customizable_key_values.keys():
		raise InvalidCustomizationException(name)
	default_value = customizable_key_values[name]
	try:
		return Customization.objects.get(name=name).value
	except Customization.DoesNotExist:
		# return default value
		return default_value
	except Exception:
		if raise_exception:
			raise
		else:
			return default_value


# This method should not be used anymore. Instead, use XCustomization.set(name, value)
def set_customization(name, value):
	customizable_key_values = CustomizationBase.all_variables()
	if name not in customizable_key_values:
		raise InvalidCustomizationException(name, value)
	if value:
		Customization.objects.update_or_create(name=name, defaults={"value": value})
	else:
		try:
			Customization.objects.get(name=name).delete()
		except Customization.DoesNotExist:
			pass


@administrator_required
@require_GET
def customization(request, key: str = "application"):
	customization_instance: CustomizationBase = CustomizationBase.get_instance(key)
	return render(request, "customizations/customizations.html", customization_instance.context())


@administrator_required
@require_POST
def customize(request, key, element=None):
	customization_instance: CustomizationBase = CustomizationBase.get_instance(key)
	if not customization_instance:
		return HttpResponseNotFound(f"Customizations with key: '{key}' not found")
	errors = customization_instance.save(request, element)
	if errors:
		messages.error(request, f"Please correct the errors below:")
		return render(
			request, "customizations/customizations.html", {"errors": errors, **customization_instance.context()}
		)
	else:
		messages.success(request, f"{customization_instance.title} settings saved successfully")
		return redirect("customization", key)
