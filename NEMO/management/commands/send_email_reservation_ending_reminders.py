from django.core.management import BaseCommand

from NEMO.views.calendar import send_email_reservation_ending_reminders


class Command(BaseCommand):
	help = (
		"Run every 15 minutes to trigger email reminder for reservations ending soon. "
		"Reservation ending reminder email has to be set in customizations for this to work."
	)

	def handle(self, *args, **options):
		send_email_reservation_ending_reminders()