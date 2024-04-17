from unittest import mock

from django.test import TestCase

from NEMO.apps.sensors.evaluators import evaluate_modbus_expression, modbus_functions
from NEMO.apps.sensors.models import Sensor, SensorCard, SensorCardCategory
from NEMO.apps.sensors.sensors import mocked_modbus_client


class ModbusInterlockTestCase(TestCase):
    def test_modbus_evaluation(self):
        # Test all modbus functions
        variables_1 = {"my_list": [100]}
        variables_2 = {"my_list": [100, 500]}
        variables_4 = {"my_list": [100, 500, 1000, 2000]}
        sensor = Sensor()
        for function_name in modbus_functions:
            sensor.formula = f"decode_string(my_list)"
            evaluate_modbus_expression(sensor, **variables_1)
            if "8" in function_name:
                sensor.formula = f"{function_name}(my_list)"
                evaluate_modbus_expression(sensor, **variables_1)
            if "16" in function_name:
                evaluate_modbus_expression(sensor, **variables_1)
            if "32" in function_name:
                evaluate_modbus_expression(sensor, **variables_2)
            elif "64" in function_name:
                evaluate_modbus_expression(sensor, **variables_4)
        sensor.formula = f"round(decode_8bit_int(my_list))"
        evaluate_modbus_expression(sensor, **variables_1)

    @mock.patch("NEMO.apps.sensors.evaluators.ModbusTcpClient", side_effect=mocked_modbus_client)
    def test_read_coils_function(self, mock_args):
        interlock_card_category = SensorCardCategory.objects.get(key="modbus_tcp")
        card = SensorCard.objects.create(server="server1.nist.gov", port=502, category=interlock_card_category)
        sensor = Sensor()
        sensor.sensor_card = card
        sensor.formula = "read_coils(1)"
        # result should be 0 or 1 (random), so test a few times to make sure we get both
        first_result = evaluate_modbus_expression(sensor)
        second_result = evaluate_modbus_expression(sensor)
        while first_result == second_result:
            second_result = evaluate_modbus_expression(sensor)
            self.assertIn(second_result, [0, 1])
