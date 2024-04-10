from django.core.management import BaseCommand

from NEMO.views.timed_services import send_email_scheduled_outage_reminders


class Command(BaseCommand):
    help = "Run every day to trigger sending email reminders for scheduled outages."

    def handle(self, *args, **options):
        send_email_scheduled_outage_reminders()
