from unittest import TestCase

from NEMO.apps.sensors.evaluators import evaluate_expression, evaluate_modbus_expression, modbus_functions


class TestAstEval(TestCase):
	def test_basic_evaluation(self):
		variables = {"te": 5, "my_list": [1, 5, 10]}
		res_1 = evaluate_expression("5*2", **variables)
		self.assertEqual(10, res_1)
		res_2 = evaluate_expression("te*2", **variables)
		self.assertEqual(10, res_2)
		res_3 = evaluate_expression("my_list[1]*2", **variables)
		self.assertEqual(10, res_3)
		res_4 = evaluate_expression("my_list[0:2]", **variables)
		self.assertEqual([1, 5], res_4)

	def test_modbus_evaluation(self):
		# Test all modbus functions
		variables_1 = {"my_list": [100]}
		variables_2 = {"my_list": [100, 500]}
		variables_4 = {"my_list": [100, 500, 1000, 2000]}
		for function_name in modbus_functions:
			evaluate_modbus_expression(f"decode_bits(my_list)", **variables_1)
			evaluate_modbus_expression(f"decode_string(my_list)", **variables_1)
			if "8" in function_name:
				evaluate_modbus_expression(f"{function_name}(my_list)", **variables_1)
			if "16" in function_name:
				evaluate_modbus_expression(f"{function_name}(my_list)", **variables_1)
			if "32" in function_name:
				evaluate_modbus_expression(f"{function_name}(my_list)", **variables_2)
			elif "64" in function_name:
				evaluate_modbus_expression(f"{function_name}(my_list)", **variables_4)
