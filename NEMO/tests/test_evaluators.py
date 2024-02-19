from unittest import TestCase

from NEMO.apps.sensors.evaluators import evaluate_modbus_expression, modbus_functions
from NEMO.evaluators import evaluate_boolean_expression, evaluate_expression, list_expression_variables


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
        res_5 = evaluate_expression("5*val", val=20)
        self.assertEqual(100, res_5)
        res_6 = evaluate_expression("5*val+val2", val=20, val2=1)
        self.assertEqual(101, res_6)
        res_7 = evaluate_expression("sum(my_list)", **variables)
        self.assertEqual(16, res_7)
        self.assertEqual(7, evaluate_expression("5+1*2"))
        self.assertEqual(7, evaluate_expression("5*1+2"))
        self.assertEqual(5, evaluate_expression("round(5.2)"))
        self.assertEqual(5.2, evaluate_expression("round(5.21, 1)"))
        self.assertEqual(6, evaluate_expression("round(5.5)"))
        self.assertEqual(6, evaluate_expression("ceil(5.2)"))
        self.assertEqual(5, evaluate_expression("floor(5.7)"))
        self.assertEqual(5, evaluate_expression("abs(-5)"))
        self.assertEqual(12, evaluate_expression("trunc(12.123)"))
        self.assertEqual(2, evaluate_expression("sqrt(4)"))

    def test_modbus_evaluation(self):
        # Test all modbus functions
        variables_1 = {"my_list": [100]}
        variables_2 = {"my_list": [100, 500]}
        variables_4 = {"my_list": [100, 500, 1000, 2000]}
        for function_name in modbus_functions:
            evaluate_modbus_expression(f"decode_string(my_list)", **variables_1)
            if "8" in function_name:
                evaluate_modbus_expression(f"{function_name}(my_list)", **variables_1)
            if "16" in function_name:
                evaluate_modbus_expression(f"{function_name}(my_list)", **variables_1)
            if "32" in function_name:
                evaluate_modbus_expression(f"{function_name}(my_list)", **variables_2)
            elif "64" in function_name:
                evaluate_modbus_expression(f"{function_name}(my_list)", **variables_4)
        evaluate_modbus_expression(f"round(decode_8bit_int(my_list))", **variables_1)

    def test_boolean_evaluation(self):
        self.assertFalse(evaluate_boolean_expression("False"))
        self.assertFalse(evaluate_boolean_expression("10 < 5"))
        self.assertFalse(evaluate_boolean_expression("5 > 10"))
        self.assertFalse(evaluate_boolean_expression("5 == 10"))
        self.assertFalse(evaluate_boolean_expression("5 * 1000 + 1 == 5002"))
        self.assertFalse(evaluate_boolean_expression("5 != 5"))
        self.assertFalse(evaluate_boolean_expression("5 > 10 > 1"))
        self.assertFalse(evaluate_boolean_expression("5 > 10 and 10 > 1"))
        self.assertFalse(evaluate_boolean_expression("True and False"))
        self.assertFalse(evaluate_boolean_expression("not True"))
        self.assertFalse(evaluate_boolean_expression("0"))
        self.assertTrue(evaluate_boolean_expression("5 > 3 > 1"))
        self.assertTrue(evaluate_boolean_expression("5 > 3 and 3 > 1"))
        self.assertTrue(evaluate_boolean_expression("True or False"))
        self.assertTrue(evaluate_boolean_expression("not False"))
        self.assertTrue(evaluate_boolean_expression("1"))
        self.assertTrue(evaluate_boolean_expression("True and True or False"))
        self.assertTrue(evaluate_boolean_expression("False or True or False"))
        self.assertTrue(evaluate_boolean_expression("True and True and True and True or False"))
        self.assertTrue(evaluate_boolean_expression("True or True and False"))
        self.assertTrue(evaluate_boolean_expression("False and True or True"))
        self.assertTrue(evaluate_boolean_expression("value > 56 and value < 76", value=60))
        self.assertFalse(evaluate_boolean_expression("False or True and False"))
        self.assertFalse(evaluate_boolean_expression("True and True and True and False"))
        self.assertFalse(evaluate_boolean_expression("value > 56 and value < 76", value=100))
        self.assertFalse(evaluate_boolean_expression("value > abs(-110)", value=100))

    def test_variable_list(self):
        self.assertEqual(list_expression_variables("value > abs(-110) + round(value2) * 2"), ["value", "value2"])
