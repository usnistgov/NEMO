from django.core.management import BaseCommand

from NEMO.apps.sensors.views import do_manage_sensor_data


class Command(BaseCommand):
    help = "Run every minute to read and manage sensors data."

    def handle(self, *args, **options):
        do_manage_sensor_data()
