import re

from django.conf import settings
from django.test import TestCase
from PIL import Image

from NEMO.utilities import capitalize, get_email_from_settings, resize_image


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

	def test_resize_image(self):
		image_path = settings.BASE_DIR + "/../resources/images/jumbotron_watermark.png"
		image = Image.open(image_path)
		width, height = image.size
		image.close()
		resized = resize_image(open(image_path, "rb"), 40)
		resized_image = Image.open(resized)
		resized_width, resized_height = resized_image.size
		if width > height:
			self.assertEqual(resized_width, 40)
		else:
			self.assertEqual(resized_height, 40)
		resized_image.close()

	def test_regex_escaping(self):
		# non escaped, no match
		self.assertFalse(re.match("test?[]]", "test?[]]"))
		# escaped, match
		self.assertTrue(re.match(re.escape("test?[]]"), "test?[]]"))
		# escaped + number
		self.assertTrue(re.match(re.escape("test?[]]") + "\d+$", "test?[]]5"))
		self.assertTrue(re.match(re.escape("test?[]]") + "\d+$", "test?[]]124"))
		# number is mandatory
		self.assertFalse(re.match(re.escape("test?[]]") + "\d+$", "test?[]]"))
