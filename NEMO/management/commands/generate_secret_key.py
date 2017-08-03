from django.core.management import BaseCommand
from django.utils.crypto import get_random_string


class Command(BaseCommand):
	help = "Writes a new Django secret key to the specified file. Use this with your settings.py file for hashing and signing. Documentation available at https://docs.djangoproject.com/en/1.11/ref/settings/#std:setting-SECRET_KEY"

	def handle(self, *positional_arguments, **named_arguments):
		try:
			f = open("django_secret_key.txt", "w")
			f.write(get_random_string(50, "abcdefghijklmnopqrstuvwxyz0123456789!@$%&=-+#(*_^)"))
			f.close()
			self.stdout.write(self.style.SUCCESS("Successfully generated a new secret key. It is strongly advised to make the file read-only and owned by the user ID that will be executing NEMO at runtime."))
		except Exception as e:
			self.stderr.write(self.style.ERROR("Something went wrong: " + str(e)))
