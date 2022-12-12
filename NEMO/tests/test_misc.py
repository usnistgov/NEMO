from django.test import TestCase

from NEMO.utilities import capitalize


class MiscTests(TestCase):

	def test_capitalize(self):
		self.assertEqual(capitalize(None), None)
		self.assertEqual(capitalize(""), "")
		self.assertEqual(capitalize("j"), "J")
		self.assertEqual(capitalize("John Doe"), "John Doe")
		self.assertEqual(capitalize("john Doe"), "John Doe")
		self.assertEqual(capitalize("john doe"), "John doe")
		self.assertEqual(capitalize("john DOE"), "John DOE")
