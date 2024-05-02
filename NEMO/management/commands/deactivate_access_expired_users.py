from django.core.management import BaseCommand

from NEMO.views.timed_services import do_deactivate_access_expired_users


class Command(BaseCommand):
    help = (
        "Run every day to deactivate some users if their access (+buffer days) has expired."
        "At least one user type option has to be set in customizations for this to work."
    )

    def handle(self, *args, **options):
        do_deactivate_access_expired_users()
