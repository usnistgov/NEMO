from unittest import TestCase

from NEMO.apps.sensors.evaluators import evaluate_expression


class TestAstEval(TestCase):
	def test(self):
		variables = {"te": 5, "my_list": [1, 5, 10]}
		res_1 = evaluate_expression("5*2", **variables)
		print(res_1)
		self.assertEqual(10, res_1)
		res_2 = evaluate_expression("te*2", **variables)
		print(res_2)
		self.assertEqual(10, res_2)
		res_3 = evaluate_expression("my_list[1]*2", **variables)
		print(res_3)
		self.assertEqual(10, res_3)
		res_4 = evaluate_expression("my_list[0:2]", **variables)
		print(res_4)
		self.assertEqual([1, 5], res_4)
