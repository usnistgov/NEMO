from django.core.management import BaseCommand

from NEMO.views.timed_services import do_create_closure_alerts


class Command(BaseCommand):
	help = (
		"Run every day to trigger the automatic alert creation for facility closures."
		"The field 'alert_days_before' has to be set on a Closure object for this to work."
	)

	def handle(self, *args, **options):
		do_create_closure_alerts()
