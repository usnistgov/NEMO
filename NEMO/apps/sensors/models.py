import datetime
import random
from logging import getLogger
from typing import List, Optional

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import QuerySet
from django.utils import timezone
from django.utils.safestring import mark_safe

from NEMO.apps.sensors.customizations import SensorCustomization
from NEMO.apps.sensors.evaluators import evaluate_boolean_expression
from NEMO.fields import MultiEmailField
from NEMO.models import InterlockCard
from NEMO.utilities import EmailCategory, format_datetime, send_mail

models_logger = getLogger(__name__)


class SensorCardCategory(models.Model):
	name = models.CharField(max_length=200, help_text="The name for this sensor card category")
	key = models.CharField(max_length=100, help_text="The key to identify this sensor card category by in sensors.py")

	class Meta:
		verbose_name_plural = "Sensor card categories"
		ordering = ["name"]

	def __str__(self):
		return str(self.name)


class SensorCard(models.Model):
	name = models.CharField(max_length=200)
	server = models.CharField(max_length=200)
	port = models.PositiveIntegerField()
	number = models.PositiveIntegerField(blank=True, null=True)
	category = models.ForeignKey(SensorCardCategory, on_delete=models.CASCADE)
	username = models.CharField(max_length=100, blank=True, null=True)
	password = models.CharField(max_length=100, blank=True, null=True)
	enabled = models.BooleanField(blank=False, null=False, default=True)

	class Meta:
		ordering = ["server", "number"]

	def __str__(self):
		card_name = self.name + ": " if self.name else ""
		return card_name + str(self.server) + (", card " + str(self.number) if self.number else "")


class SensorCategory(models.Model):
	name = models.CharField(max_length=200, help_text="The name for this sensor category")
	parent = models.ForeignKey(
		"SensorCategory", related_name="children", null=True, blank=True, on_delete=models.SET_NULL
	)

	def is_leaf(self):
		return not self.children.exists()

	def all_children(self) -> List:
		if not self.children.exists():
			return []
		all_children = []
		for child in self.children.all():
			all_children.extend([child, *child.all_children()])
		return all_children

	def ancestors(self, include_self: bool = False) -> List:
		if not self.parent:
			return []
		ancestors = [*self.parent.ancestors(False), self.parent]
		if include_self:
			ancestors.append(self)
		return ancestors

	def alert_triggered(self):
		for sensor in self.sensor_set.all():
			if sensor.alert_triggered():
				return True
		for child in self.children.all():
			if child.alert_triggered():
				return True
		return False

	def __str__(self):
		return str(self.name)

	class Meta:
		verbose_name_plural = "Sensor categories"
		ordering = ["name"]


class Sensor(models.Model):
	name = models.CharField(max_length=200)
	visible = models.BooleanField(
		default=True, help_text="Specifies whether this sensor is visible in the sensor dashboard"
	)
	sensor_card = models.ForeignKey(SensorCard, blank=True, null=True, on_delete=models.CASCADE)
	interlock_card = models.ForeignKey(InterlockCard, blank=True, null=True, on_delete=models.CASCADE)
	sensor_category = models.ForeignKey(SensorCategory, blank=True, null=True, on_delete=models.SET_NULL)
	data_label = models.CharField(blank=True, null=True, max_length=200, help_text="Label for graph and table data")
	data_prefix = models.CharField(blank=True, null=True, max_length=100, help_text="Prefix for sensor data values")
	data_suffix = models.CharField(blank=True, null=True, max_length=100, help_text="Suffix for sensor data values")
	unit_id = models.PositiveIntegerField(null=True, blank=True)
	read_address = models.PositiveIntegerField(null=True, blank=True)
	number_of_values = models.PositiveIntegerField(null=True, blank=True, validators=[MinValueValidator(1)])
	formula = models.TextField(
		null=True,
		blank=True,
		help_text=mark_safe(
			"Enter a formula to compute for this sensor values. The list of registers read is available as variable <b>registers</b>. Specific functions can be used based on the sensor type. See documentation for details."
		),
	)
	read_frequency = models.PositiveIntegerField(
		default=5,
		validators=[MaxValueValidator(1440), MinValueValidator(0)],
		help_text="Enter the read frequency in minutes. Every 2 hours = 120, etc. Max value is 1440 min (24hrs). Use 0 to disable sensor data read.",
	)

	@property
	def card(self):
		return self.sensor_card or self.interlock_card

	def read_data(self, raise_exception=False):
		from NEMO.apps.sensors import sensors

		return sensors.get(self.card.category, raise_exception).read_values(self, raise_exception)

	def last_data_point(self):
		return SensorData.objects.filter(sensor=self).latest("created_date")

	def clean(self):
		from NEMO.apps.sensors import sensors

		if not self.sensor_card and not self.interlock_card:
			raise ValidationError({"sensor_card": "Please select either a sensor or interlock card"})
		if self.sensor_card or self.interlock_card:
			# Throw an error if no sensor implementation is present
			try:
				sensors.get(self.card.category, raise_exception=True)
			except Exception as e:
				key = "sensor_card" if self.sensor_card else "interlock_card"
				raise ValidationError({key: str(e)})
		if (
				not self.formula
				and self.read_address is not None
				and self.number_of_values is not None
				and self.number_of_values > 1
		):
			raise ValidationError({"formula": "This field is required when reading multiple values"})
		if self.formula:
			# Use random values to test the formula
			registers = []
			if self.read_address is not None and self.number_of_values:
				for i in range(self.number_of_values):
					registers.append(random.randint(0, 1000))
			else:
				registers = [random.randint(0, 1000)]
			try:
				sensors.get(self.card.category, raise_exception=True).evaluate_expression(self.formula, registers)
			except Exception as e:
				raise ValidationError({"formula": str(e)})

	def alert_triggered(self) -> bool:
		for alert_qs in SensorAlert.sensor_alert_filter(sensor=self):
			if alert_qs.filter(triggered_on__isnull=False).exists():
				return True
		return False

	def __str__(self):
		return self.name


class SensorData(models.Model):
	sensor = models.ForeignKey(Sensor, on_delete=models.CASCADE)
	created_date = models.DateTimeField(auto_now_add=True)
	value = models.FloatField()

	def display_value(self):
		return f"{self.sensor.data_prefix + ' ' if self.sensor.data_prefix else ''}{self.value}{' ' + self.sensor.data_suffix if self.sensor.data_suffix else ''}"

	class Meta:
		verbose_name_plural = "Sensor data"
		ordering = ["-created_date"]


class SensorAlertLog(models.Model):
	sensor = models.ForeignKey(Sensor, on_delete=models.CASCADE)
	time = models.DateTimeField(auto_now_add=True)
	value = models.FloatField(null=True, blank=True)
	reset = models.BooleanField(default=False)
	condition = models.TextField(null=True, blank=True)
	no_data = models.BooleanField(default=False)

	def description(self):
		return get_alert_description(self.time, self.reset, self.condition, self.no_data, self.value)

	class Meta:
		ordering = ["-time"]


class SensorAlert(models.Model):
	enabled = models.BooleanField(default=True)
	sensor = models.ForeignKey(Sensor, on_delete=models.CASCADE)
	trigger_no_data = models.BooleanField(
		default=False, help_text="Check this box to trigger this alert when no data is available"
	)
	trigger_condition = models.TextField(
		null=True,
		blank=True,
		help_text=mark_safe(
			"The trigger condition for this alert. The sensor value is available as a variable named <b>value</b>. e.g. value == 42 or value > 42."
		),
	)
	triggered_on = models.DateTimeField(null=True, blank=True)

	class Meta:
		abstract = True

	def _reset_alert(self, alert_time, value):
		# Only reset if alert was previously triggered
		if self.triggered_on:
			self.set_alert_time(time=None)
			self.log_alert(alert_time, reset=True, value=value)
			self.reset_alert(alert_time, value)

	def _trigger_alert(self, alert_time, value):
		# Only trigger if alert is not currently triggered
		if not self.triggered_on:
			self.set_alert_time(time=alert_time)
			self.log_alert(alert_time, reset=False, value=value)
			self.trigger_alert(alert_time, value)

	def clean(self):
		if not self.trigger_condition and not self.trigger_no_data:
			raise ValidationError(
				{
					"trigger_condition": "Please enter a trigger condition or set this alert to trigger when there is no data"
				}
			)
		if self.trigger_condition:
			# Use a random value to test the formula
			value = random.uniform(0, 100)
			try:
				evaluate_boolean_expression(self.trigger_condition, value=value)
			except Exception as e:
				raise ValidationError({"trigger_condition": str(e)})

	def set_alert_time(self, time: Optional[datetime.datetime]):
		self.triggered_on = time
		self.save()

	def log_alert(self, time: datetime.datetime, reset: bool = False, value: float = None):
		SensorAlertLog.objects.create(
			time=time,
			condition=self.trigger_condition,
			sensor=self.sensor,
			value=value,
			reset=reset,
			no_data=self.trigger_no_data,
		)

	def process(self, sensor_data: SensorData = None):
		# 1. Alert should trigger on condition and when no data is present
		# 2. Alert should trigger on condition only
		# 3. Alert should trigger only when no data is present
		now = timezone.now()
		value: float = sensor_data.value if sensor_data else None
		if self.trigger_condition and self.trigger_no_data:
			# Case #1: alert triggered when either no data OR data and condition is met
			if not value or evaluate_boolean_expression(self.trigger_condition, value=value):
				self._trigger_alert(now, value)
			# Case #1: alert reset when both data is present AND condition is not met
			else:
				self._reset_alert(now, value)
		elif self.trigger_condition:
			if value:
				# Case #2: alert triggered when data is present AND condition is met
				if evaluate_boolean_expression(self.trigger_condition, value=value):
					self._trigger_alert(now, value)
				# Case #2: alert reset when data is present AND condition is not met
				else:
					self._reset_alert(now, value)
		else:
			# Case #3: alert triggered when no data
			if not value:
				self._trigger_alert(now, value)
			# Case #3: alert reset when data is present
			else:
				self._reset_alert(now, value)

	def reset_alert(self, alert_time: datetime.datetime, value: float = None):
		# This should be implemented in children of this class
		pass

	def trigger_alert(self, alert_time: datetime.datetime, value: float = None):
		# This should be implemented in children of this class
		pass

	@classmethod
	def sensor_alert_filter(cls, enabled=True, sensor=None) -> List[QuerySet]:
		sensor_alert_qs = []
		for sub_class in cls.__subclasses__():
			sub_filter = sub_class.objects.all()
			if enabled is not None:
				sub_filter = sub_filter.filter(enabled=enabled)
			if sensor:
				sub_filter = sub_filter.filter(sensor=sensor)
			sensor_alert_qs.append(sub_filter)
		return sensor_alert_qs


class SensorAlertEmail(SensorAlert):
	additional_emails = MultiEmailField(
		null=True, blank=True, help_text="Additional email address to contact when this alert is triggered. A comma-separated list can be used."
	)

	def reset_alert(self, alert_time: datetime.datetime, value: float = None):
		subject = f"Alert reset for {self.sensor.name}"
		message = get_alert_description(alert_time, True, self.trigger_condition, self.trigger_no_data, value)
		self.send(subject, message)

	def trigger_alert(self, alert_time: datetime.datetime, value: float = None):
		subject = f"Alert triggered for {self.sensor.name}"
		message = get_alert_description(alert_time, False, self.trigger_condition, self.trigger_no_data, value)
		self.send(subject, message)

	def send(self, subject, message):
		email_to = SensorCustomization.get("sensor_alert_emails")
		recipients = [e for e in email_to.split(",") if e]
		if self.additional_emails:
			recipients.extend(self.additional_emails)
		if recipients:
			send_mail(
				subject=subject,
				content=message,
				from_email=settings.SERVER_EMAIL,
				to=recipients,
				email_category=EmailCategory.SENSORS,
			)


def get_alert_description(time, reset: bool, condition: str, no_data: bool, value: float):
	if condition and value:
		if reset:
			trigger_reason = f'the value ({value}) didn\'t meet the alert condition: "{condition}" anymore'
		else:
			trigger_reason = f'the condition: "{condition}" was met with value={value}'
	elif no_data and not value:
		trigger_reason = f"there was no data"
	elif value and reset:
		trigger_reason = f"the sensor sent back value={value}"
	else:
		trigger_reason = None
	alert_description = f"This alert was {'reset' if reset else 'triggered'} on {format_datetime(time)}"
	if trigger_reason:
		alert_description += f" because {trigger_reason}."
	return alert_description
