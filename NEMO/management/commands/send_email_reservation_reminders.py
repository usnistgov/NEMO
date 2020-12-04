from django.core.management import BaseCommand

from NEMO.views.calendar import send_email_reservation_reminders


class Command(BaseCommand):
	help = (
		"Run every 15 minutes to trigger email reminder for reservations. "
		"Reservation reminder and reservation warning emails have to be set in customizations for this to work."
	)

	def handle(self, *args, **options):
		send_email_reservation_reminders()