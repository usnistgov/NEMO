from abc import ABC, abstractmethod
from logging import getLogger
from typing import Dict, List

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from pymodbus.client.sync import ModbusTcpClient

from NEMO.apps.sensors.admin import SensorAdminForm, SensorCardAdminForm
from NEMO.apps.sensors.models import Sensor as Sensor_model, SensorCardCategory, SensorData

sensors_logger = getLogger(__name__)


class Sensor(ABC):
	"""
	This interface allows for customization of Sensors features.
	The only method that has to be implemented is the abstract method "do_read_values"

	The method "clean_sensor_card" can be implemented to set validation rules for the sensor card with the same category

	The sensor type should be set at the end of this file in the dictionary. The key is the key from SensorCardCategory, the value is the Sensor implementation.
	"""

	def clean_sensor_card(self, sensor_card_form: SensorCardAdminForm):
		pass

	def clean_sensor(self, sensor_form: SensorAdminForm):
		pass

	def read_values(self, sensor: Sensor_model, raise_exception=False):
		if not sensor.card.enabled:
			sensors_logger.warning(f"{sensor.name} sensor interface mocked out because sensor card is disabled.")
			return True

		error_message = ""
		data_value = None
		try:
			registers = self.do_read_values(sensor)
			data_value = sensor.evaluate(registers=registers)
		except Exception as error:
			sensors_logger.error(error)
			error_message = str(error)
			if raise_exception:
				raise

		if not error_message and data_value:
			SensorData.objects.create(sensor=sensor, value=data_value)

	@abstractmethod
	def do_read_values(self, sensor: Sensor_model) -> List:
		pass


class ModbusTcpSensor(Sensor):
	def clean_sensor(self, sensor_form: SensorAdminForm):
		read_address = sensor_form.cleaned_data["read_address"]
		number_of_values = sensor_form.cleaned_data["number_of_values"]
		error = {}
		if not read_address:
			error["read_address"] = _("This field is required.")
		if not number_of_values:
			error["number_of_values"] = _("This field is required.")
		if error:
			raise ValidationError(error)

	def do_read_values(self, sensor: Sensor_model) -> List:
		client = ModbusTcpClient(sensor.card.server, port=sensor.card.port)
		client.connect()
		kwargs = {"unit": sensor.unit_id} if sensor.unit_id is not None else {}
		read_response = client.read_holding_registers(sensor.read_address, sensor.number_of_values, **kwargs)
		if read_response.isError():
			raise Exception(str(read_response))
		return read_response.registers


class NoOpSensor(Sensor):
	def do_read_values(self, sensor: Sensor_model) -> List:
		pass


def get(category: SensorCardCategory, raise_exception=False):
	"""	Returns the corresponding sensor implementation, and raises an exception if not found. """
	sensor_impl = sensors.get(category.key, False)
	if not sensor_impl:
		if raise_exception:
			raise Exception(
				f"There is no sensor implementation for category: {category.name}. Please add one in sensors.py"
			)
		else:
			return NoOpSensor()
	else:
		return sensor_impl


sensors: Dict[str, Sensor] = {"modbus_tcp": ModbusTcpSensor()}
