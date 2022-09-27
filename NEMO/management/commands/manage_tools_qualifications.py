from django.core.management import BaseCommand

from NEMO.views.calendar import send_email_tool_qualification_expiration


class Command(BaseCommand):
	help = (
		"Run every day to warn or disqualify tools for users if they have not used them in a while."
		"Disqualify days and tool qualification expiration email have to be set in customizations for this to work."
	)

	def handle(self, *args, **options):
		send_email_tool_qualification_expiration()
