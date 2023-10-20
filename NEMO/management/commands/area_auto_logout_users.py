from django.core.management import BaseCommand

from NEMO.views.timed_services import do_auto_logout_users


class Command(BaseCommand):
    help = (
        "Run every minute to trigger the automatic area logout."
        "The field 'auto_logout_time' has to be set on an Area object for this to work."
    )

    def handle(self, *args, **options):
        do_auto_logout_users()
