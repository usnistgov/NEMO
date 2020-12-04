from django.core.management import BaseCommand

from NEMO.views.calendar import send_email_usage_reminders


class Command(BaseCommand):
	help = (
		"Run every hour to trigger email usage reminders. "
		"Reservation reminder and reservation warning emails have to be set in customizations for this to work."
	)

	def add_arguments(self, parser):
		parser.add_argument('exclude_project_ids', nargs='*', type=int, help='list of project ids to exclude')

	def handle(self, *args, **options):
		send_email_usage_reminders(options.get('exclude_project_ids'))