from django.conf import settings
from django.test import TestCase

from NEMO.utilities import capitalize, get_email_from_settings


class MiscTests(TestCase):

	def test_capitalize(self):
		self.assertEqual(capitalize(None), None)
		self.assertEqual(capitalize(""), "")
		self.assertEqual(capitalize("j"), "J")
		self.assertEqual(capitalize("John Doe"), "John Doe")
		self.assertEqual(capitalize("john Doe"), "John Doe")
		self.assertEqual(capitalize("john doe"), "John doe")
		self.assertEqual(capitalize("john DOE"), "John DOE")

	def test_server_email(self):
		default_from = "email@example.com"
		self.assertEqual(get_email_from_settings(), settings.SERVER_EMAIL)
		with self.settings(DEFAULT_FROM_EMAIL=default_from):
			self.assertEqual(get_email_from_settings(), default_from)

