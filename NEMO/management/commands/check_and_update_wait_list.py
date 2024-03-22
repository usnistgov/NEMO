from django.core.management import BaseCommand

from NEMO.views.timed_services import do_check_and_update_wait_list


class Command(BaseCommand):
    help = (
        "Run every minute to update tool wait list."
        "Wait list notification email and slot time to expiration have to be set in customizations for this to work correctly."
    )

    def handle(self, *args, **options):
        do_check_and_update_wait_list()
