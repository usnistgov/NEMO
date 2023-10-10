from django.core.management import BaseCommand

from NEMO.views.timed_services import do_manage_tool_qualifications


class Command(BaseCommand):
	help = (
		"Run every day to warn or disqualify tools for users if they have not used them in a while."
		"Disqualify days and tool qualification expiration email have to be set in customizations for this to work."
	)

	def handle(self, *args, **options):
		do_manage_tool_qualifications()
