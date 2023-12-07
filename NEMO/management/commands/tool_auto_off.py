import datetime

from django.core.management import BaseCommand, CommandError
from django.utils import timezone

from NEMO.models import Reservation, UsageEvent, Interlock


class Command(BaseCommand):
    help = (
        "Turn off all tools that are used past the end-grace-period (default 5 minutes) of a reservation. "
        "Won't turn off tools that are started in the start-grace-period (default 30 minutes) before a reservation."
    )

    problems = 0

    def add_arguments(self, parser):
        parser.add_argument("--start-grace-period", nargs="?", type=int, default=30, help="Grace period before next reservation starts in minutes")
        parser.add_argument("--end-grace-period", nargs="?", type=int, default=5, help="Grace period after reservation ends in minutes")

    def handle(self, *args, **options):
        self.start_grace_period = options["start_grace_period"]
        self.end_grace_period = options["end_grace_period"]
        self.stdout.write(f"Running tool_auto_off (start_grace_period={self.start_grace_period}, end_grace_period={self.end_grace_period})")
        self._turn_tools_off_used_past_grace_period()

        if self.problems > 0:
            raise CommandError(f"{self.problems} problem(s) occurred!")

    def _turn_tools_off_used_past_grace_period(self):
        active_usage_events = UsageEvent.objects.filter(end__isnull=True)
        self.stdout.write(f"{len(active_usage_events)} active usage event(s) to check")

        for usage_event in active_usage_events:
            self._check_usage_event(usage_event)

    def _check_usage_event(self, usage_event: UsageEvent):
        self.stdout.write(f'Checking active UsageEvent #{usage_event.id} where tool is "{usage_event.tool}" and user is {usage_event.user}...', ending="")

        if usage_event.tool:
            self._check_usage_event_that_has_tool(usage_event)
        else:
            self.stdout.write("There is no tool associated to this usage event...Skipping")

    def _check_usage_event_that_has_tool(self, usage_event: UsageEvent):
        reservation = self._get_reservation(usage_event)

        if not reservation:
            self._turn_tool_off(usage_event)
        else:
            self.stdout.write(f"Tool in use for Reservation #{reservation.id}...Skipping")

    def _get_reservation(self, usage_event):
        """
        For the usage event, get the reservation that is currently active or will be active within
        start_grace_period minutes
        """
        start = timezone.now() + datetime.timedelta(minutes=self.start_grace_period)
        end = timezone.now() - datetime.timedelta(minutes=self.end_grace_period)
        return Reservation.objects.filter(
            tool=usage_event.tool,
            user=usage_event.user,
            cancelled=False,
            start__lte=start,
            end__gte=end
        ).first()

    def _turn_tool_off(self, usage_event: UsageEvent):
        usage_event.end = timezone.now()
        usage_event.save()

        formatted_end_time = usage_event.end.strftime("%H:%M:%S on %Y-%m-%d")

        if usage_event.tool.interlock and usage_event.tool.interlock.lock():
            self.stdout.write(f'Tool turned off at {formatted_end_time}')
        else:
            self.problems += 1
            self.stdout.write(f"Problem turning off the tool, however the interlock was still locked and the usage event ended at {formatted_end_time}")