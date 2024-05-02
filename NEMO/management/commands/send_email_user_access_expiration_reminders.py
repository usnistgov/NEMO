from django.core.management import BaseCommand

from NEMO.views.timed_services import send_email_user_access_expiration_reminders


class Command(BaseCommand):
    help = (
        "Run every day to send an email reminder to users having their access expiring."
        "User access expiration reminder email and reminder days have to be set in customizations for this to work."
    )

    def handle(self, *args, **options):
        send_email_user_access_expiration_reminders()
