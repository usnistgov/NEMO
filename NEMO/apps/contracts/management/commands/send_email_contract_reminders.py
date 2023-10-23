from django.core.management import BaseCommand

from NEMO.apps.contracts.views.contracts import send_email_contract_reminders


class Command(BaseCommand):
    help = "Run every day to send contracts email reminders for Service contracts and Contractor agreements."

    def handle(self, *args, **options):
        send_email_contract_reminders()
