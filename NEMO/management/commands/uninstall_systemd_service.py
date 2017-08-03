from django.core.management import BaseCommand
from os import remove


class Command(BaseCommand):
	help = "Uninstalls NEMO as a systemd service"

	def handle(self, file_name):
		try:
			remove('/etc/systemd/system/nemo.service')
			self.stdout.write(self.style.SUCCESS("The systemd NEMO service was successfully uninstalled"))
		except Exception as e:
			self.stderr.write(self.style.ERROR("Something went wrong: " + str(e)))
