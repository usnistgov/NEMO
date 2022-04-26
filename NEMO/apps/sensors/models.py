import random
from logging import getLogger

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.safestring import mark_safe

from NEMO.models import InterlockCard

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
	even_port = models.PositiveIntegerField(blank=True, null=True)
	odd_port = models.PositiveIntegerField(blank=True, null=True)
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

	class Meta:
		verbose_name_plural = "Sensor categories"
		ordering = ["name"]

	def __str__(self):
		return str(self.name)


class Sensor(models.Model):
	name = models.CharField(max_length=200)
	sensor_card = models.ForeignKey(SensorCard, blank=True, null=True, on_delete=models.CASCADE)
	interlock_card = models.ForeignKey(InterlockCard, blank=True, null=True, on_delete=models.CASCADE)
	sensor_category = models.ForeignKey(SensorCategory, blank=True, null=True, on_delete=models.SET_NULL)
	data_prefix = models.CharField(blank=True, null=True, max_length=100)
	data_suffix = models.CharField(blank=True, null=True, max_length=100)
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
