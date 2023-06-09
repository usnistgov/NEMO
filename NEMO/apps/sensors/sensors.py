from abc import ABC, abstractmethod
from logging import getLogger
from typing import Dict, List

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from pymodbus.client import ModbusTcpClient

from NEMO.apps.sensors.admin import SensorAdminForm, SensorCardAdminForm
from NEMO.apps.sensors.evaluators import evaluate_expression, evaluate_modbus_expression
from NEMO.apps.sensors.models import Sensor as Sensor_model, SensorAlert, SensorCardCategory, SensorData

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
			warning_message = f"{sensor.name} sensor interface mocked out because sensor card is disabled."
			sensors_logger.warning(warning_message)
			return warning_message

		data = None
		try:
			registers = self.do_read_values(sensor)
			data_value = self.evaluate_sensor(sensor, registers=registers)
			if data_value:
				data = SensorData.objects.create(sensor=sensor, value=data_value)
				process_alerts(sensor, data)
				return data
		except Exception as error:
			sensors_logger.error(error)
			process_alerts(sensor, data)
			if raise_exception:
				raise
			else:
				return error

	def evaluate_sensor(self, sensor, registers, raise_exception=True):
		try:
			if sensor.formula:
				return self.evaluate_expression(sensor.formula, registers)
			else:
				return next(iter(registers or []), None)
		except Exception as e:
			sensors_logger.warning(e)
			if raise_exception:
				raise

	def evaluate_expression(self, formula, registers):
		return evaluate_expression(formula, registers=registers)

	@abstractmethod
	def do_read_values(self, sensor: Sensor_model) -> List:
		pass


def process_alerts(sensor: Sensor, sensor_data: SensorData = None):
	try:
		sensor_alerts = []
		for sub_class in SensorAlert.__subclasses__():
			sensor_alerts.extend(sub_class.objects.filter(enabled=True, sensor=sensor))
		for alert in sensor_alerts:
			alert.process(sensor_data)
	except Exception as e:
		sensors_logger.error(e)


class ModbusTcpSensor(Sensor):
	def clean_sensor(self, sensor_form: SensorAdminForm):
		read_address = sensor_form.cleaned_data["read_address"]
		number_of_values = sensor_form.cleaned_data["number_of_values"]
		error = {}
		if read_address is None:
			error["read_address"] = _("This field is required.")
		if not number_of_values:
			error["number_of_values"] = _("This field is required.")
		if error:
			raise ValidationError(error)

	def do_read_values(self, sensor: Sensor_model) -> List:
		client = ModbusTcpClient(sensor.card.server, port=sensor.card.port)
		try:
			valid_connection = client.connect()
			if not valid_connection:
				raise Exception(f"Connection to server {sensor.card.server}:{sensor.card.port} could not be established")
			kwargs = {"slave": sensor.unit_id} if sensor.unit_id is not None else {}
			read_response = client.read_holding_registers(sensor.read_address, sensor.number_of_values, **kwargs)
			if read_response.isError():
				raise Exception(f"Error with sensor {sensor.name}: {str(read_response)}")
			return read_response.registers
		finally:
			client.close()

	def evaluate_expression(self, formula, registers):
		# Here we are using an expanded evaluator which includes modbus specific functions
		return evaluate_modbus_expression(formula, registers=registers)


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
