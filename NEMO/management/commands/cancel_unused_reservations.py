from django.core.management import BaseCommand

from NEMO.views.calendar import do_cancel_unused_reservations


class Command(BaseCommand):
	help = (
		"Run every minute to cancel unused reservations and mark them as missed. "
		"Only applicable to areas or tools having a missed reservation threshold value."
	)

	def handle(self, *args, **options):
		do_cancel_unused_reservations()