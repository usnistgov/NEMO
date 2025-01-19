from django.core.management import BaseCommand

from NEMO.views.timed_services import do_email_csv_interlock_status_report


class Command(BaseCommand):
    help = "Run to send an interlock status report to the users with the given usernames."

    def add_arguments(self, parser):
        parser.add_argument("usernames", nargs="+", type=str, help="list of usernames to send the report to")

    def handle(self, *args, **options):
        do_email_csv_interlock_status_report(options.get("usernames"))
