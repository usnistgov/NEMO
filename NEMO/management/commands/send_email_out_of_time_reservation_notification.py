from django.core.management import BaseCommand

from NEMO.views.calendar import send_email_out_of_time_reservation_notification


class Command(BaseCommand):
	help = (
		"Run every minute to trigger email out of time in area notification. "
		"Out of time reservation email has to be set in customizations for this to work."
	)

	def handle(self, *args, **options):
		send_email_out_of_time_reservation_notification()