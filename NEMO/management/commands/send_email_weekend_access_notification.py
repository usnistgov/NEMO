from django.core.management import BaseCommand

from NEMO.views.access_requests import send_email_weekend_access_notification


class Command(BaseCommand):
	help = (
		"Run every hour to trigger the email notification for weekend access."
		"Weekend access request email has to be set in customizations for this to work."
	)

	def handle(self, *args, **options):
		send_email_weekend_access_notification()
