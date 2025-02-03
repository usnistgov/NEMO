from datetime import timedelta
from time import sleep

from django.test import TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from NEMO.models import Account, Area, EmailLog, Project, Reservation, Tool, UsageEvent, User, UserPreferences
from NEMO.tests.test_utilities import login_as
from NEMO.utilities import format_datetime
from NEMO.views.customization import ToolCustomization


class ReservationTestCase(TransactionTestCase):
    def setUp(self):
        self.staff = User.objects.create(username="mctest", first_name="Testy", last_name="McTester", is_staff=True)
        self.area = Area.objects.create(name="test_area", category="Imaging", reservation_warning=2)
        self.tool = Tool.objects.create(
            name="test_tool",
            primary_owner=self.staff,
            _category="Imaging",
            location="bay 1",
            requires_area_access=self.area,
        )
        account = Account.objects.create(name="account1")
        self.project = Project.objects.create(name="project1", account=account)
        self.staff = User.objects.create(username="staff", first_name="Staff", last_name="Member", is_staff=True)
        self.consumer = User.objects.create(
            username="jsmith", first_name="John", last_name="Smith", training_required=False, email="jsmith@test.com"
        )
        self.consumer.qualifications.add(self.tool)
        self.consumer.projects.add(self.project)
        self.consumer.save()
        self.staff.projects.add(self.project)
        # make sure it's on
        ToolCustomization.set("tool_freed_time_notify_next_reservation_enabled", "enabled")

    def test_cancel_reservation(self):
        prefs: UserPreferences = self.consumer.get_preferences()
        prefs.tool_freed_time_notifications.set([self.tool])
        # default is 7 days in the future, more than 2 hours
        start = timezone.now() + timedelta(hours=1)
        end = start + timedelta(hours=3)
        reservation = Reservation.objects.create(
            tool=self.tool,
            start=start,
            end=end,
            user=self.staff,
            creator=self.staff,
            project=self.project,
            short_notice=False,
        )
        login_as(self.client, self.staff)
        self.client.post(reverse("cancel_reservation", args=[reservation.id]), follow=True)
        # Wait a second since the freed time notification is asynchronous
        sleep(0.5)
        minutes = reservation.duration().total_seconds() / 60
        # start of freed time is start
        start_of_freed_time = start
        self.assertTrue(Reservation.objects.get(id=reservation.id).cancelled, True)
        self.assertEqual(
            EmailLog.objects.filter(to=self.consumer.email, subject__startswith=f"[{self.tool.name}]").first().subject,
            email_subject(self.tool, minutes, start_of_freed_time),
        )

    def test_cancel_reservation_same_user(self):
        # user whose reservation it is doesn't get an email
        prefs: UserPreferences = self.consumer.get_preferences()
        prefs.tool_freed_time_notifications.set([self.tool])
        # default is 7 days in the future, more than 2 hours
        start = timezone.now() + timedelta(hours=1)
        end = start + timedelta(hours=3)
        reservation = Reservation.objects.create(
            tool=self.tool,
            start=start,
            end=end,
            user=self.consumer,
            creator=self.consumer,
            project=self.project,
            short_notice=False,
        )
        login_as(self.client, self.consumer)
        self.client.post(reverse("cancel_reservation", args=[reservation.id]), follow=True)
        # Wait a second since the freed time notification is asynchronous
        sleep(0.5)
        minutes = reservation.duration().total_seconds() / 60
        minutes = f"{minutes:0.0f}"
        self.assertTrue(Reservation.objects.get(id=reservation.id).cancelled, True)
        self.assertFalse(
            EmailLog.objects.filter(
                to=self.consumer.email, subject__startswith=f"[{self.tool.name}] {minutes}"
            ).exists()
        )

    def test_cancel_reservation_not_tool(self):
        prefs: UserPreferences = self.consumer.get_preferences()
        prefs.tool_freed_time_notifications.set([self.tool])
        # default is 7 days in the future, more than 2 hours
        start = timezone.now() + timedelta(hours=1)
        end = start + timedelta(hours=3)
        reservation = Reservation.objects.create(
            area=self.area,
            start=start,
            end=end,
            user=self.consumer,
            creator=self.consumer,
            project=self.project,
            short_notice=False,
        )
        login_as(self.client, self.consumer)
        self.client.post(reverse("cancel_reservation", args=[reservation.id]), follow=True)
        # Wait a second since the freed time notification is asynchronous
        sleep(0.5)
        minutes = reservation.duration().total_seconds() / 60
        minutes = f"{minutes:0.0f}"
        self.assertTrue(Reservation.objects.get(id=reservation.id).cancelled, True)
        self.assertFalse(
            EmailLog.objects.filter(
                to=self.consumer.email, subject__startswith=f"[{self.tool.name}] {minutes}"
            ).exists()
        )

    def test_cancel_reservation_past(self):
        # if the reservation is in the past, no notifications
        prefs: UserPreferences = self.consumer.get_preferences()
        prefs.tool_freed_time_notifications.set([self.tool])
        # default is 7 days in the future, more than 2 hours
        start = timezone.now() + timedelta(days=-1) + timedelta(hours=1)
        end = start + timedelta(hours=3)
        reservation = Reservation.objects.create(
            tool=self.tool,
            start=start,
            end=end,
            user=self.staff,
            creator=self.staff,
            project=self.project,
            short_notice=False,
        )
        login_as(self.client, self.staff)
        self.client.post(reverse("cancel_reservation", args=[reservation.id]), follow=True)
        # Wait a second since the freed time notification is asynchronous
        sleep(0.5)
        minutes = reservation.duration().total_seconds() / 60
        minutes = f"{minutes:0.0f}"
        self.assertTrue(Reservation.objects.get(id=reservation.id).cancelled, True)
        self.assertFalse(
            EmailLog.objects.filter(to=self.consumer.email, subject__startswith=f"[{self.tool.name}] {minutes}")
        )

    def test_shrink_reservation(self):
        prefs: UserPreferences = self.consumer.get_preferences()
        prefs.tool_freed_time_notifications.set([self.tool])
        # default is 7 days in the future, more than 2 hours
        start = timezone.now() + timedelta(hours=1)
        end = start + timedelta(hours=6)
        reservation = Reservation.objects.create(
            tool=self.tool,
            start=start,
            end=end,
            user=self.staff,
            creator=self.staff,
            project=self.project,
            short_notice=False,
        )
        minutes = 130
        login_as(self.client, self.staff)
        self.client.post(reverse("resize_reservation"), {"delta": -minutes, "id": reservation.id}, follow=True)
        # Wait a second since the freed time notification is asynchronous
        sleep(0.5)
        # shrunk 130 minutes of the end of a 6-hour reservation, so time freed starts at end - 130
        start_of_freed_time = end - timedelta(minutes=minutes)
        self.assertTrue(Reservation.objects.get(id=reservation.id).cancelled, True)
        self.assertEqual(
            EmailLog.objects.filter(to=self.consumer.email, subject__startswith=f"[{self.tool.name}]").first().subject,
            email_subject(self.tool, minutes, start_of_freed_time),
        )

    def test_extend_reservation(self):
        # When extending a reservation, no notifications should be sent
        prefs: UserPreferences = self.consumer.get_preferences()
        prefs.tool_freed_time_notifications.set([self.tool])
        # default is 7 days in the future, more than 2 hours
        start = timezone.now() + timedelta(hours=1)
        end = start + timedelta(hours=3)
        reservation = Reservation.objects.create(
            tool=self.tool,
            start=start,
            end=end,
            user=self.staff,
            creator=self.staff,
            project=self.project,
            short_notice=False,
        )
        minutes = 130
        login_as(self.client, self.staff)
        self.client.post(reverse("resize_reservation"), {"delta": minutes, "id": reservation.id}, follow=True)
        # Wait a second since the freed time notification is asynchronous
        sleep(0.5)
        self.assertTrue(Reservation.objects.get(id=reservation.id).cancelled, True)
        self.assertFalse(
            EmailLog.objects.filter(
                to=self.consumer.email, subject__startswith=f"[{self.tool.name}] {minutes}"
            ).exists()
        )

    def test_move_reservation_future(self):
        prefs: UserPreferences = self.consumer.get_preferences()
        prefs.tool_freed_time_notifications.set([self.tool])
        # default is 7 days in the future, more than 2 hours
        start = timezone.now() + timedelta(hours=1)
        end = start + timedelta(hours=3)
        reservation = Reservation.objects.create(
            tool=self.tool,
            start=start,
            end=end,
            user=self.staff,
            creator=self.staff,
            project=self.project,
            short_notice=False,
        )
        minutes = 130
        login_as(self.client, self.staff)
        self.client.post(reverse("move_reservation"), {"delta": minutes, "id": reservation.id}, follow=True)
        # Wait a second since the freed time notification is asynchronous
        sleep(0.5)
        # moved 130 minutes later a 7-hour reservation, so time freed starts at start
        start_of_freed_time = start
        self.assertTrue(Reservation.objects.get(id=reservation.id).cancelled, True)
        self.assertEqual(
            EmailLog.objects.filter(to=self.consumer.email, subject__startswith=f"[{self.tool.name}]").first().subject,
            email_subject(self.tool, minutes, start_of_freed_time),
        )

    def test_move_reservation_past(self):
        prefs: UserPreferences = self.consumer.get_preferences()
        prefs.tool_freed_time_notifications.set([self.tool])
        # default is 7 days in the future, more than 2 hours
        start = timezone.now() + timedelta(hours=7)
        end = start + timedelta(hours=3)
        reservation = Reservation.objects.create(
            tool=self.tool,
            start=start,
            end=end,
            user=self.staff,
            creator=self.staff,
            project=self.project,
            short_notice=False,
        )
        minutes = -130
        login_as(self.client, self.staff)
        self.client.post(reverse("move_reservation"), {"delta": minutes, "id": reservation.id}, follow=True)
        # Wait a second since the freed time notification is asynchronous
        sleep(0.5)
        # moved 130 minutes earlier a 7-hour reservation, so time freed starts at end - 130
        start_of_freed_time = end + timedelta(minutes=minutes)
        self.assertTrue(Reservation.objects.get(id=reservation.id).cancelled, True)
        self.assertEqual(
            EmailLog.objects.filter(to=self.consumer.email, subject__startswith=f"[{self.tool.name}]").first().subject,
            email_subject(self.tool, minutes, start_of_freed_time),
        )

    def test_notify_next_reservation_no_notifications(self):
        consumer_2 = User.objects.create(
            username="jsmith2",
            first_name="John2",
            last_name="Smith2",
            training_required=False,
            email="jsmith2@test.com",
        )
        # start an hour ago, so we can simulate shortening
        start = timezone.now() - timedelta(hours=1)
        end = start + timedelta(hours=3)
        reservation = Reservation.objects.create(
            tool=self.tool,
            start=start,
            end=end,
            user=consumer_2,
            creator=consumer_2,
            project=self.project,
            short_notice=False,
        )
        # engage the tool then disengage
        UsageEvent.objects.create(
            operator=consumer_2,
            user=consumer_2,
            tool=self.tool,
            project=self.project,
        )
        login_as(self.client, consumer_2)
        self.client.post(reverse("disable_tool", args=[self.tool.id]), follow=True)
        # Wait a second since the freed time notification is asynchronous
        sleep(0.5)
        # no one should have been notified
        self.assertTrue(Reservation.objects.get(id=reservation.id).shortened, True)
        self.assertFalse(EmailLog.objects.exists())

    def test_notify_next_reservation_no_notifications_too_late(self):
        consumer_2 = User.objects.create(
            username="jsmith2",
            first_name="John2",
            last_name="Smith2",
            training_required=False,
            email="jsmith2@test.com",
        )
        # start an hour ago, so we can simulate shortening
        start = timezone.now() - timedelta(hours=1)
        end = start + timedelta(hours=3)
        reservation = Reservation.objects.create(
            tool=self.tool,
            start=start,
            end=end,
            user=consumer_2,
            creator=consumer_2,
            project=self.project,
            short_notice=False,
        )
        # Add a reservation more than 1h later for another user
        next_reservation = Reservation.objects.create(
            tool=self.tool,
            start=end + timedelta(hours=1.5),
            end=end + timedelta(hours=3.5),
            user=self.consumer,
            creator=self.consumer,
            project=self.project,
            short_notice=False,
        )
        # engage the tool then disengage
        UsageEvent.objects.create(
            operator=consumer_2,
            user=consumer_2,
            tool=self.tool,
            project=self.project,
        )
        login_as(self.client, consumer_2)
        self.client.post(reverse("disable_tool", args=[self.tool.id]), follow=True)
        # Wait a second since the freed time notification is asynchronous
        sleep(0.5)
        # still nothing (too late)
        self.assertTrue(Reservation.objects.get(id=reservation.id).shortened, True)
        self.assertFalse(EmailLog.objects.exists())

    def test_notify_next_reservation_no_notification_too_little_freed_time(self):
        consumer_2 = User.objects.create(
            username="jsmith2",
            first_name="John2",
            last_name="Smith2",
            training_required=False,
            email="jsmith2@test.com",
        )
        # start an hour ago, so we can simulate shortening, but only freeing less than 15 minutes
        start = timezone.now() - timedelta(hours=1)
        end = timezone.now() + timedelta(minutes=14)
        reservation = Reservation.objects.create(
            tool=self.tool,
            start=start,
            end=end,
            user=consumer_2,
            creator=consumer_2,
            project=self.project,
            short_notice=False,
        )
        # new reservation closer to it (starts less than an hour after original ended)
        next_reservation = Reservation.objects.create(
            tool=self.tool,
            start=end + timedelta(hours=0.5),
            end=end + timedelta(hours=3.5),
            user=self.consumer,
            creator=self.consumer,
            project=self.project,
            short_notice=False,
        )
        # engage the tool then disengage
        UsageEvent.objects.create(
            operator=consumer_2,
            user=consumer_2,
            tool=self.tool,
            project=self.project,
        )
        login_as(self.client, consumer_2)
        self.client.post(reverse("disable_tool", args=[self.tool.id]), follow=True)
        # Wait a second since the freed time notification is asynchronous
        sleep(0.5)
        # Should
        # still nothing (too little freed time)
        self.assertTrue(Reservation.objects.get(id=reservation.id).shortened, True)
        self.assertFalse(EmailLog.objects.exists())

    def test_notify_next_reservation_notification(self):
        consumer_2 = User.objects.create(
            username="jsmith2",
            first_name="John2",
            last_name="Smith2",
            training_required=False,
            email="jsmith2@test.com",
        )
        # start an hour ago, so we can simulate shortening
        start = timezone.now() - timedelta(hours=1)
        end = start + timedelta(hours=3)
        reservation = Reservation.objects.create(
            tool=self.tool,
            start=start,
            end=end,
            user=consumer_2,
            creator=consumer_2,
            project=self.project,
            short_notice=False,
        )
        # new reservation closer to it (starts less than an hour after original ended)
        next_reservation = Reservation.objects.create(
            tool=self.tool,
            start=end + timedelta(hours=0.5),
            end=end + timedelta(hours=3.5),
            user=self.consumer,
            creator=self.consumer,
            project=self.project,
            short_notice=False,
        )
        # engage the tool then disengage
        UsageEvent.objects.create(
            operator=consumer_2,
            user=consumer_2,
            tool=self.tool,
            project=self.project,
        )
        login_as(self.client, consumer_2)
        self.client.post(reverse("disable_tool", args=[self.tool.id]), follow=True)
        # Wait a second since the freed time notification is asynchronous
        sleep(0.5)
        # This time it should work
        minutes = (timezone.now() - reservation.end).total_seconds() // 60
        start_of_freed_time = reservation.end + timedelta(minutes=minutes)
        self.assertEqual(
            EmailLog.objects.filter(to=self.consumer.email, subject__startswith=f"[{self.tool.name}]").first().subject,
            email_subject(self.tool, minutes, start_of_freed_time),
        )

    def test_notify_next_reservation_notification_first_one(self):
        consumer_2 = User.objects.create(
            username="jsmith2",
            first_name="John2",
            last_name="Smith2",
            training_required=False,
            email="jsmith2@test.com",
        )
        # start an hour ago, so we can simulate shortening
        start = timezone.now() - timedelta(hours=1)
        end = start + timedelta(hours=3)
        reservation = Reservation.objects.create(
            tool=self.tool,
            start=start,
            end=end,
            user=consumer_2,
            creator=consumer_2,
            project=self.project,
            short_notice=False,
        )
        # multiple new reservation closer to it (starts less than an hour after original ended)
        Reservation.objects.create(
            tool=self.tool,
            start=end + timedelta(hours=0.7),
            end=end + timedelta(hours=0.8),
            user=self.staff,
            creator=self.staff,
            project=self.project,
            short_notice=False,
        )
        Reservation.objects.create(
            tool=self.tool,
            start=end + timedelta(hours=0.5),
            end=end + timedelta(hours=0.6),
            user=self.consumer,
            creator=self.consumer,
            project=self.project,
            short_notice=False,
        )
        Reservation.objects.create(
            tool=self.tool,
            start=end + timedelta(hours=0.6),
            end=end + timedelta(hours=0.7),
            user=self.staff,
            creator=self.staff,
            project=self.project,
            short_notice=False,
        )
        # engage the tool then disengage
        UsageEvent.objects.create(
            operator=consumer_2,
            user=consumer_2,
            tool=self.tool,
            project=self.project,
        )
        login_as(self.client, consumer_2)
        self.client.post(reverse("disable_tool", args=[self.tool.id]), follow=True)
        # Wait a second since the freed time notification is asynchronous
        sleep(0.5)
        # This time it should work, but only for the first one (consumer)
        self.assertFalse(EmailLog.objects.filter(to=self.staff.email).exists())
        minutes = (timezone.now() - reservation.end).total_seconds() // 60
        start_of_freed_time = reservation.end + timedelta(minutes=minutes)
        self.assertEqual(
            EmailLog.objects.filter(to=self.consumer.email, subject__startswith=f"[{self.tool.name}]").first().subject,
            email_subject(self.tool, minutes, start_of_freed_time),
        )

    def test_notify_next_reservation_notifications_not_enabled(self):
        # turn them off
        ToolCustomization.set("tool_freed_time_notify_next_reservation_enabled", "")
        consumer_2 = User.objects.create(
            username="jsmith2",
            first_name="John2",
            last_name="Smith2",
            training_required=False,
            email="jsmith2@test.com",
        )
        # start an hour ago, so we can simulate shortening
        start = timezone.now() - timedelta(hours=1)
        end = start + timedelta(hours=3)
        reservation = Reservation.objects.create(
            tool=self.tool,
            start=start,
            end=end,
            user=consumer_2,
            creator=consumer_2,
            project=self.project,
            short_notice=False,
        )
        # new reservation closer to it (starts less than an hour after original ended)
        next_reservation = Reservation.objects.create(
            tool=self.tool,
            start=end + timedelta(hours=0.5),
            end=end + timedelta(hours=3.5),
            user=self.consumer,
            creator=self.consumer,
            project=self.project,
            short_notice=False,
        )
        # engage the tool then disengage
        UsageEvent.objects.create(
            operator=consumer_2,
            user=consumer_2,
            tool=self.tool,
            project=self.project,
        )
        login_as(self.client, consumer_2)
        self.client.post(reverse("disable_tool", args=[self.tool.id]), follow=True)
        # Wait a second since the freed time notification is asynchronous
        sleep(0.5)
        # no one should have been notified
        self.assertTrue(Reservation.objects.get(id=reservation.id).shortened, True)
        self.assertFalse(EmailLog.objects.exists())

    def test_notify_next_reservation_too_little_customization(self):
        consumer_2 = User.objects.create(
            username="jsmith2",
            first_name="John2",
            last_name="Smith2",
            training_required=False,
            email="jsmith2@test.com",
        )
        # min freed time of a bit more than 2 hours
        ToolCustomization.set("tool_freed_time_notify_next_reservation_min_freed_time", "121")
        # start an hour ago, so we can simulate shortening
        start = timezone.now() - timedelta(hours=1)
        end = start + timedelta(hours=3)
        reservation = Reservation.objects.create(
            tool=self.tool,
            start=start,
            end=end,
            user=consumer_2,
            creator=consumer_2,
            project=self.project,
            short_notice=False,
        )
        # new reservation closer to it (starts less than an hour after original ended)
        next_reservation = Reservation.objects.create(
            tool=self.tool,
            start=end + timedelta(hours=0.5),
            end=end + timedelta(hours=3.5),
            user=self.consumer,
            creator=self.consumer,
            project=self.project,
            short_notice=False,
        )
        # engage the tool then disengage
        UsageEvent.objects.create(
            operator=consumer_2,
            user=consumer_2,
            tool=self.tool,
            project=self.project,
        )
        login_as(self.client, consumer_2)
        self.client.post(reverse("disable_tool", args=[self.tool.id]), follow=True)
        # Wait a second since the freed time notification is asynchronous
        sleep(0.5)
        # still nothing (too little freed time)
        self.assertTrue(Reservation.objects.get(id=reservation.id).shortened, True)
        self.assertFalse(EmailLog.objects.exists())

    def test_notify_next_reservation_later_customization_notification(self):
        consumer_2 = User.objects.create(
            username="jsmith2",
            first_name="John2",
            last_name="Smith2",
            training_required=False,
            email="jsmith2@test.com",
        )
        # ok with starting later (2 hours later here)
        ToolCustomization.set("tool_freed_time_notify_next_reservation_starts_within", "2")
        # start an hour ago, so we can simulate shortening
        start = timezone.now() - timedelta(hours=1)
        end = start + timedelta(hours=3)
        reservation = Reservation.objects.create(
            tool=self.tool,
            start=start,
            end=end,
            user=consumer_2,
            creator=consumer_2,
            project=self.project,
            short_notice=False,
        )
        # new reservation closer to it (starts 2 hours after original ended)
        next_reservation = Reservation.objects.create(
            tool=self.tool,
            start=end + timedelta(hours=2),
            end=end + timedelta(hours=3.5),
            user=self.consumer,
            creator=self.consumer,
            project=self.project,
            short_notice=False,
        )
        # engage the tool then disengage
        UsageEvent.objects.create(
            operator=consumer_2,
            user=consumer_2,
            tool=self.tool,
            project=self.project,
        )
        login_as(self.client, consumer_2)
        self.client.post(reverse("disable_tool", args=[self.tool.id]), follow=True)
        # Wait a second since the freed time notification is asynchronous
        sleep(0.5)
        # This time it should work
        minutes = (timezone.now() - reservation.end).total_seconds() // 60
        start_of_freed_time = reservation.end + timedelta(minutes=minutes)
        self.assertEqual(
            EmailLog.objects.filter(to=self.consumer.email, subject__startswith=f"[{self.tool.name}]").first().subject,
            email_subject(self.tool, minutes, start_of_freed_time),
        )


def email_subject(tool, minutes, date):
    formatted_start = format_datetime(date)
    formatted_time = f"{abs(minutes):0.0f}"
    return f"[{tool.name}] {formatted_time} minutes freed starting {formatted_start}"
