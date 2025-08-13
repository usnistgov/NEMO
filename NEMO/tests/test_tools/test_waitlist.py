from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from NEMO.models import Reservation, Tool, ToolWaitList, UsageEvent, User
from NEMO.tests.test_utilities import create_user_and_project, login_as
from NEMO.views.customization import EmailsCustomization, ToolCustomization, store_media_file
from NEMO.views.timed_services import do_check_and_update_wait_list
from NEMO.views.tool_control import do_exit_wait_list


class ToolWaitListTestCase(TestCase):
    def setUp(self) -> None:
        EmailsCustomization.set("user_office_email_address", "user_office_email_address@wait_list_test.com")
        store_media_file(
            open("resources/emails/tool_wait_list_notification_email.html", "r"), "wait_list_notification_email.html"
        )

    def test_user_enter_wait_list_regular_mode_fail(self):
        self.enter_wait_list_mode_fail(reverse("enter_wait_list"), Tool.OperationMode.REGULAR)

    def test_user_enter_wait_list_regular_mode_kiosk_fail(self):
        self.enter_wait_list_mode_fail(reverse("enter_wait_list_from_kiosk"), Tool.OperationMode.REGULAR, True)

    def test_user_enter_wait_list_wait_list_mode_pass(self):
        self.enter_wait_list_mode_pass(reverse("enter_wait_list"), Tool.OperationMode.WAIT_LIST)

    def test_user_enter_wait_list_wait_list_mode_kiosk_pass(self):
        self.enter_wait_list_mode_pass(reverse("enter_wait_list_from_kiosk"), Tool.OperationMode.WAIT_LIST)

    def test_user_enter_wait_list_hybrid_mode_pass(self):
        self.enter_wait_list_mode_pass(reverse("enter_wait_list"), Tool.OperationMode.HYBRID)

    def test_user_enter_wait_list_hybrid_mode_kiosk_pass(self):
        self.enter_wait_list_mode_pass(reverse("enter_wait_list_from_kiosk"), Tool.OperationMode.HYBRID)

    def test_user_enter_wait_list_twice(self):
        self.user_enter_wait_list_twice(reverse("enter_wait_list"))

    def test_user_enter_wait_list_kiosk_twice(self):
        self.user_enter_wait_list_twice(reverse("enter_wait_list_from_kiosk"), True)

    def test_user_exit_wait_list(self):
        self.exit_wait_list_pass(reverse("enter_wait_list"), reverse("exit_wait_list"))

    def test_user_exit_wait_list_kiosk(self):
        self.exit_wait_list_pass(reverse("enter_wait_list_from_kiosk"), reverse("exit_wait_list_from_kiosk"))

    def test_user_exit_wait_list_not_in_wait_list(self):
        self.exit_wait_list_not_in_wait_list(reverse("exit_wait_list"))

    def test_user_exit_wait_list_kiosk_not_in_wait_list(self):
        self.exit_wait_list_not_in_wait_list(reverse("exit_wait_list_from_kiosk"), True)

    def test_wait_list_mode_reservation(self):
        time_to_expiration_saved, reservation_buffer_saved = get_configuration()
        try:
            (
                time_to_expiration,
                reservation_buffer,
                user,
                project,
                user1,
                project1,
                user2,
                project2,
                tool,
                usage,
                email_outbox_count,
                current_wait_list,
                user1_wait_list_entry,
                end_usage_date,
            ) = self.starting_sequence(Tool.OperationMode.WAIT_LIST, 5, 10)

            # reservation starting in 5 minutes (within reservation buffer threshold)
            reservation_start = end_usage_date + timezone.timedelta(minutes=reservation_buffer - 2)
            create_reservation(user, tool, reservation_start, reservation_start + timezone.timedelta(minutes=30))

            # run timed service as end_usage_date
            time = run_time_service_as(end_usage_date)

            # User 1 should be sent an email notification
            email_outbox_count += 1
            self.check_entry_user_and_timer_start_date_and_email_count(
                user1_wait_list_entry, user1, end_usage_date, email_outbox_count
            )

            # Expire user1 then user2
            self.expiring_user1_then_user2_sequence(
                tool, user1_wait_list_entry, user2, time, time_to_expiration, email_outbox_count
            )

        finally:
            setup_configuration(time_to_expiration_saved, reservation_buffer_saved)

    def test_wait_list_mode_user_exit(self):
        self.user_exit(Tool.OperationMode.WAIT_LIST)

    def test_hybrid_mode_user_exit(self):
        self.user_exit(Tool.OperationMode.HYBRID)

    def test_wait_list_mode_user_exit_out_of_order(self):
        self.user_exit_out_of_order(Tool.OperationMode.WAIT_LIST)

    def test_hybrid_mode_user_exit_out_of_order(self):
        self.user_exit_out_of_order(Tool.OperationMode.HYBRID)

    def test_wait_list_mode_no_usage(self):
        self.no_usage(Tool.OperationMode.WAIT_LIST)

    def test_wait_list_mode_usage_during_turn(self):
        self.usage_during_turn(Tool.OperationMode.WAIT_LIST)

    def test_hybrid_mode_no_usage(self):
        self.no_usage(Tool.OperationMode.HYBRID)

    def test_hybrid_mode_usage_during_turn(self):
        self.usage_during_turn(Tool.OperationMode.HYBRID)

    def test_hybrid_mode_reservation(self):
        time_to_expiration_saved, reservation_buffer_saved = get_configuration()
        try:
            (
                time_to_expiration,
                reservation_buffer,
                user,
                project,
                user1,
                project1,
                user2,
                project2,
                tool,
                usage,
                email_outbox_count,
                current_wait_list,
                user1_wait_list_entry,
                end_usage_date,
            ) = self.starting_sequence(Tool.OperationMode.HYBRID, 5, 10)

            # reservation starting within reservation buffer threshold 2 thirds of the way
            reservation_start = end_usage_date + timezone.timedelta(minutes=reservation_buffer * (2 / 3))
            reservation_end = reservation_start + timezone.timedelta(minutes=30)
            create_reservation(user, tool, reservation_start, reservation_end)

            # run timed service halfway within buffer zone
            run_time_service_as(end_usage_date + timezone.timedelta(minutes=reservation_buffer / 2))

            # During the reservation buffer zone, wait list check should be skipped
            self.check_entry_user_and_timer_start_date_and_email_count(
                user1_wait_list_entry, user1, None, email_outbox_count
            )

            # run timed service 5 minutes before reservation end
            run_time_service_as(reservation_end - timezone.timedelta(minutes=5))

            # During the reservation period, wait list check should be skipped
            self.check_entry_user_and_timer_start_date_and_email_count(
                user1_wait_list_entry, user1, None, email_outbox_count
            )

            # run timed service when reservation ends
            time = run_time_service_as(reservation_end)

            # After the reservation period, turn available date should be reservation end date and email notification sent
            email_outbox_count += 1
            self.check_entry_user_and_timer_start_date_and_email_count(
                user1_wait_list_entry, user1, reservation_end, email_outbox_count
            )

            # Expire user1 then user2
            self.expiring_user1_then_user2_sequence(
                tool, user1_wait_list_entry, user2, time, time_to_expiration, email_outbox_count
            )

        finally:
            setup_configuration(time_to_expiration_saved, reservation_buffer_saved)

    def test_hybrid_mode_reservation_missed(self):
        time_to_expiration_saved, reservation_buffer_saved = get_configuration()
        try:
            missed_threshold = 5
            (
                time_to_expiration,
                reservation_buffer,
                user,
                project,
                user1,
                project1,
                user2,
                project2,
                tool,
                usage,
                email_outbox_count,
                current_wait_list,
                user1_wait_list_entry,
                end_usage_date,
            ) = self.starting_sequence(Tool.OperationMode.HYBRID, 5, 10, missed_threshold)

            # reservation starting within reservation buffer threshold 2 thirds of the way
            reservation_start = end_usage_date + timezone.timedelta(minutes=reservation_buffer * (2 / 3))
            reservation_end = reservation_start + timezone.timedelta(minutes=30)
            reservation = create_reservation(user, tool, reservation_start, reservation_end)

            # run timed service halfway within the reservation missed threshold
            run_time_service_as(reservation_start + timezone.timedelta(minutes=missed_threshold / 2))

            # within missed threshold, wait list check should be skipped
            self.check_entry_user_and_timer_start_date_and_email_count(
                user1_wait_list_entry, user1, None, email_outbox_count
            )

            # Missed reservation
            missed_time = reservation_start + timezone.timedelta(minutes=missed_threshold)
            reservation.missed = True
            reservation.save()

            # Run timed service after missed threshold
            time = run_time_service_as(missed_time)

            # After the reservation is missed, turn available date should be missed date and email notification sent
            email_outbox_count += 1
            self.check_entry_user_and_timer_start_date_and_email_count(
                user1_wait_list_entry, user1, missed_time, email_outbox_count
            )

            # Expire user1 then user2
            self.expiring_user1_then_user2_sequence(
                tool, user1_wait_list_entry, user2, time, time_to_expiration, email_outbox_count
            )

        finally:
            setup_configuration(time_to_expiration_saved, reservation_buffer_saved)

    def test_hybrid_mode_reservation_and_usage(self):
        time_to_expiration_saved, reservation_buffer_saved = get_configuration()
        try:
            (
                time_to_expiration,
                reservation_buffer,
                user,
                project,
                user1,
                project1,
                user2,
                project2,
                tool,
                usage,
                email_outbox_count,
                current_wait_list,
                user1_wait_list_entry,
                end_usage_date,
            ) = self.starting_sequence(Tool.OperationMode.HYBRID, 5, 10)

            # reservation starting within reservation buffer threshold 2 thirds of the way
            reservation_start = end_usage_date + timezone.timedelta(minutes=reservation_buffer * (2 / 3))
            reservation_end = reservation_start + timezone.timedelta(minutes=30)
            create_reservation(user, tool, reservation_start, reservation_end)

            # run timed service halfway within buffer zone
            run_time_service_as(end_usage_date + timezone.timedelta(minutes=reservation_buffer / 2))

            # During the reservation buffer zone, wait list check should be skipped
            self.check_entry_user_and_timer_start_date_and_email_count(
                user1_wait_list_entry, user1, None, email_outbox_count
            )

            # run timed service 5 minutes before reservation end
            run_time_service_as(reservation_end - timezone.timedelta(minutes=5))

            # During the reservation period, wait list check should be skipped
            self.check_entry_user_and_timer_start_date_and_email_count(
                user1_wait_list_entry, user1, None, email_outbox_count
            )

            # Usage has started during the reservation period (5minutes before the end)
            second_usage = create_usage(user, project, tool, reservation_end - timezone.timedelta(minutes=5), None)

            # run timed service after reservation end
            time = run_time_service_as(reservation_end + timezone.timedelta(minutes=10))

            # After reservation end, wait list check should be skipped because there is a usage going on
            self.check_entry_user_and_timer_start_date_and_email_count(
                user1_wait_list_entry, user1, None, email_outbox_count
            )

            # End second usage
            second_usage_end = end_usage(second_usage, time + timezone.timedelta(minutes=5))

            # run timed service after second usage end
            time = run_time_service_as(second_usage_end + timezone.timedelta(minutes=10))

            # After the second usage ends, turn available date should be second usage end date and email notification sent
            email_outbox_count += 1
            self.check_entry_user_and_timer_start_date_and_email_count(
                user1_wait_list_entry, user1, second_usage_end, email_outbox_count
            )

            # Expire user1 then user2
            self.expiring_user1_then_user2_sequence(
                tool, user1_wait_list_entry, user2, time, time_to_expiration, email_outbox_count
            )

        finally:
            setup_configuration(time_to_expiration_saved, reservation_buffer_saved)

    def test_hybrid_mode_consecutive_reservations_with_gap(self):
        time_to_expiration_saved, reservation_buffer_saved = get_configuration()
        try:
            (
                time_to_expiration,
                reservation_buffer,
                user,
                project,
                user1,
                project1,
                user2,
                project2,
                tool,
                usage,
                email_outbox_count,
                current_wait_list,
                user1_wait_list_entry,
                end_usage_date,
            ) = self.starting_sequence(Tool.OperationMode.HYBRID, 5, 10)

            # reservation one starting within reservation buffer threshold 2 thirds of the way
            reservation_one_start = end_usage_date + timezone.timedelta(minutes=reservation_buffer * (2 / 3))
            reservation_one_end = reservation_one_start + timezone.timedelta(minutes=30)
            create_reservation(user, tool, reservation_one_start, reservation_one_end)

            # reservation two starting in reservation_buffer + 2 minutes gap after reservation one
            reservation_two_start = reservation_one_end + timezone.timedelta(minutes=reservation_buffer + 2)
            reservation_two_end = reservation_two_start + timezone.timedelta(minutes=30)
            create_reservation(user, tool, reservation_two_start, reservation_two_end)

            # run timed service halfway within buffer zone of reservation one
            run_time_service_as(end_usage_date + timezone.timedelta(minutes=reservation_buffer / 2))

            # During the reservation one buffer zone, wait list check should be skipped
            self.check_entry_user_and_timer_start_date_and_email_count(
                user1_wait_list_entry, user1, None, email_outbox_count
            )

            # run timed service 5 minutes before reservation one end
            run_time_service_as(reservation_one_end - timezone.timedelta(minutes=5))

            # During the reservation one period, wait list check should be skipped
            self.check_entry_user_and_timer_start_date_and_email_count(
                user1_wait_list_entry, user1, None, email_outbox_count
            )

            # run timed service in gap between reservation one and reservation two buffer zone
            run_time_service_as(reservation_one_end + timezone.timedelta(minutes=1))

            # During the gap between reservation one and reservation two
            # turn available should be end of reservation one and email notification sent
            email_outbox_count += 1
            self.check_entry_user_and_timer_start_date_and_email_count(
                user1_wait_list_entry, user1, reservation_one_end, email_outbox_count
            )

            # run timed service in reservation two (5 minutes before the end)
            run_time_service_as(reservation_two_end - timezone.timedelta(minutes=1))

            # During the reservation two period (5 minutes before the end), wait list check should be skipped
            self.check_entry_user_and_timer_start_date_and_email_count(
                user1_wait_list_entry, user1, reservation_one_end, email_outbox_count
            )

            # run timed service after reservation two end
            time = run_time_service_as(reservation_two_end)

            # After the reservation two has ended
            # turn available should be reservation two end and email notification sent
            email_outbox_count += 1
            self.check_entry_user_and_timer_start_date_and_email_count(
                user1_wait_list_entry, user1, reservation_two_end, email_outbox_count
            )

            # Expire user1 then user2
            self.expiring_user1_then_user2_sequence(
                tool, user1_wait_list_entry, user2, time, time_to_expiration, email_outbox_count
            )

        finally:
            setup_configuration(time_to_expiration_saved, reservation_buffer_saved)

    def enter_wait_list(self, user, tool):
        login_as(self.client, user)
        response = self.client.post(
            reverse("enter_wait_list"),
            {"tool_id": tool.id},
        )
        self.assertEqual(response.status_code, 200)

    def exit_wait_list(self, user, tool, time):
        wait_list_entry = ToolWaitList.objects.filter(tool=tool, expired=False, deleted=False, user=user)
        do_exit_wait_list(wait_list_entry, time)

    def setup_entities(self, mode, missed_threshold=None):
        user, project = create_user_and_project(True)
        user1, project1 = create_user_and_project(True)
        user2, project2 = create_user_and_project(True)
        tool = create_tool("WaitList Test Tool", mode, missed_threshold)
        usage = create_usage(user, project, tool, timezone.now() - timezone.timedelta(minutes=10), None)
        return user, project, user1, project1, user2, project2, tool, usage

    def check_wail_list_size_and_top(self, tool, user, size):
        current_wait_list = tool.current_wait_list()
        wait_list_entry = tool.top_wait_list_entry()
        self.assertEqual(current_wait_list.count(), size)
        self.assertEqual(wait_list_entry.user.id, user)
        return current_wait_list, wait_list_entry

    def check_entry_user_and_timer_start_date_and_email_count(self, wait_list_entry, user, time, email_count):
        wait_list_entry.refresh_from_db()
        self.assertEqual(wait_list_entry.last_turn_available_at, time)
        self.assertEqual(wait_list_entry.user.id, user.id)
        self.assertEqual(wait_list_entry.expired, False)
        self.assertEqual(len(mail.outbox), email_count)

    def check_entry_has_expired(self, tool, wait_list_entry, new_size):
        wait_list_entry.refresh_from_db()
        current_wait_list = tool.current_wait_list()
        self.assertEqual(wait_list_entry.expired, True)
        self.assertEqual(current_wait_list.count(), new_size)

    def starting_sequence(self, mode, time_to_expiration, reservation_buffer, missed_threshold=None):
        time_to_expiration, reservation_buffer = setup_configuration(time_to_expiration, reservation_buffer)
        user, project, user1, project1, user2, project2, tool, usage = self.setup_entities(mode, missed_threshold)
        email_outbox_count = 0

        # User 1 enter wait list
        self.enter_wait_list(user1, tool)

        # User 2 enter wait list
        self.enter_wait_list(user2, tool)

        # Check wait list size and top
        current_wait_list, user1_wait_list_entry = self.check_wail_list_size_and_top(tool, user1.id, 2)

        now = timezone.now()

        # end current usage
        end_usage_date = end_usage(usage, now)

        return (
            time_to_expiration,
            reservation_buffer,
            user,
            project,
            user1,
            project1,
            user2,
            project2,
            tool,
            usage,
            email_outbox_count,
            current_wait_list,
            user1_wait_list_entry,
            end_usage_date,
        )

    def expiring_user1_then_user2_sequence(
        self, tool, user1_entry, user2, time, time_to_expiration, email_outbox_count
    ):
        # After time_to_expiration minutes
        # This tick expires user1
        time = run_time_service_as(time + timezone.timedelta(minutes=time_to_expiration))
        # This tick bumps user2 to the top of the wait list
        time = run_time_service_as(time)

        # Expect user1 to be removed from the wait list (EXPIRED=TRUE)
        self.check_entry_has_expired(tool, user1_entry, 1)

        # Expect user2 to be at the top of wait list and sent an email notification
        user2_wait_list_entry = tool.top_wait_list_entry()
        email_outbox_count += 1
        self.check_entry_user_and_timer_start_date_and_email_count(
            user2_wait_list_entry, user2, time, email_outbox_count
        )

        # After time_to_expiration minutes
        time = run_time_service_as(time + timezone.timedelta(minutes=time_to_expiration))

        # Expect user2 to be removed from the wait list (EXPIRED=TRUE)
        self.check_entry_has_expired(tool, user2_wait_list_entry, 0)

    def no_usage(self, mode):
        time_to_expiration_saved, reservation_buffer_saved = get_configuration()
        try:
            (
                time_to_expiration,
                reservation_buffer,
                user,
                project,
                user1,
                project1,
                user2,
                project2,
                tool,
                usage,
                email_outbox_count,
                current_wait_list,
                user1_wait_list_entry,
                end_usage_date,
            ) = self.starting_sequence(mode, 5, 10)

            # run timed service as end_usage_date
            time = run_time_service_as(end_usage_date)

            # User 1 should be sent an email notification
            email_outbox_count += 1
            self.check_entry_user_and_timer_start_date_and_email_count(
                user1_wait_list_entry, user1, end_usage_date, email_outbox_count
            )

            # Expire user1 then user2
            self.expiring_user1_then_user2_sequence(
                tool, user1_wait_list_entry, user2, time, time_to_expiration, email_outbox_count
            )

        finally:
            setup_configuration(time_to_expiration_saved, reservation_buffer_saved)

    def usage_during_turn(self, mode):
        time_to_expiration_saved, reservation_buffer_saved = get_configuration()
        try:
            (
                time_to_expiration,
                reservation_buffer,
                user,
                project,
                user1,
                project1,
                user2,
                project2,
                tool,
                usage,
                email_outbox_count,
                current_wait_list,
                user1_wait_list_entry,
                end_usage_date,
            ) = self.starting_sequence(mode, 5, 10)

            # run timed service as end_usage_date
            time = run_time_service_as(end_usage_date)

            # User 1 should be sent an email notification
            email_outbox_count += 1
            self.check_entry_user_and_timer_start_date_and_email_count(
                user1_wait_list_entry, user1, end_usage_date, email_outbox_count
            )

            # After 2 minutes a random user starts using the tool (skip line)
            time = time + timezone.timedelta(minutes=2)
            second_usage = create_usage(user, project, tool, time, None)

            # run timed service after 10 minutes
            time = run_time_service_as(time + timezone.timedelta(minutes=10))

            # User 1 should stay on top of the list and not be sent an email notification
            self.check_entry_user_and_timer_start_date_and_email_count(
                user1_wait_list_entry, user1, end_usage_date, email_outbox_count
            )

            # end second usage 2 minutes later
            end_second_usage_date = end_usage(second_usage, time + timezone.timedelta(minutes=2))

            # run timed service
            time = run_time_service_as(end_second_usage_date)

            # User 1 should be sent another email notification and turn available date should be updated
            email_outbox_count += 1
            self.check_entry_user_and_timer_start_date_and_email_count(
                user1_wait_list_entry, user1, end_second_usage_date, email_outbox_count
            )

            # Expire user1 then user2
            self.expiring_user1_then_user2_sequence(
                tool, user1_wait_list_entry, user2, time, time_to_expiration, email_outbox_count
            )

        finally:
            setup_configuration(time_to_expiration_saved, reservation_buffer_saved)

    def user_exit(self, mode):
        time_to_expiration_saved, reservation_buffer_saved = get_configuration()
        try:
            (
                time_to_expiration,
                reservation_buffer,
                user,
                project,
                user1,
                project1,
                user2,
                project2,
                tool,
                usage,
                email_outbox_count,
                current_wait_list,
                user1_wait_list_entry,
                end_usage_date,
            ) = self.starting_sequence(mode, 5, 10)

            # run timed service as end_usage_date
            time = run_time_service_as(end_usage_date)

            # User 1 should be sent an email notification
            email_outbox_count += 1
            self.check_entry_user_and_timer_start_date_and_email_count(
                user1_wait_list_entry, user1, end_usage_date, email_outbox_count
            )

            # user 1 exits the wait list 1 minute after the end_usage_date
            time_of_exit = end_usage_date + timezone.timedelta(minutes=1)
            self.exit_wait_list(user1, tool, time_of_exit)
            user1_wait_list_entry.refresh_from_db()

            # After halfway through expiration time for user2 (time user1 exits + time_to_expiration / 2)
            time = run_time_service_as(
                user1_wait_list_entry.date_exited + timezone.timedelta(minutes=time_to_expiration / 2)
            )

            # Expect user2 to be at the top of wait list and sent an email notification
            user2_wait_list_entry = tool.top_wait_list_entry()
            email_outbox_count += 1
            self.check_entry_user_and_timer_start_date_and_email_count(
                user2_wait_list_entry, user2, time_of_exit, email_outbox_count
            )

            # After time_to_expiration minutes
            run_time_service_as(user1_wait_list_entry.date_exited + timezone.timedelta(minutes=time_to_expiration))

            # Expect user2 to be removed from the wait list (EXPIRED=TRUE)
            self.check_entry_has_expired(tool, user2_wait_list_entry, 0)

        finally:
            setup_configuration(time_to_expiration_saved, reservation_buffer_saved)

    def user_exit_out_of_order(self, mode):
        time_to_expiration_saved, reservation_buffer_saved = get_configuration()
        try:
            (
                time_to_expiration,
                reservation_buffer,
                user,
                project,
                user1,
                project1,
                user2,
                project2,
                tool,
                usage,
                email_outbox_count,
                current_wait_list,
                user1_wait_list_entry,
                end_usage_date,
            ) = self.starting_sequence(mode, 5, 10)

            user3, project3 = create_user_and_project(True)

            # User 3 enter wait list
            self.enter_wait_list(user3, tool)

            # run timed service as end_usage_date
            run_time_service_as(end_usage_date)

            # User 1 should be sent an email notification
            email_outbox_count += 1
            self.check_entry_user_and_timer_start_date_and_email_count(
                user1_wait_list_entry, user1, end_usage_date, email_outbox_count
            )

            # user 2 exits the wait list 1 minute after the end_usage_date
            time_of_user2_exit = end_usage_date + timezone.timedelta(minutes=1)
            self.exit_wait_list(user2, tool, time_of_user2_exit)

            # user 1 exits the wait list 2 minute after the end_usage_date
            time_of_user1_exit = end_usage_date + timezone.timedelta(minutes=2)
            self.exit_wait_list(user1, tool, time_of_user1_exit)
            user1_wait_list_entry.refresh_from_db()

            # After 3 minutes
            time = run_time_service_as(end_usage_date + timezone.timedelta(minutes=3))

            # Expect user3 to be at the top of wait list and sent an email notification
            user3_wait_list_entry = tool.top_wait_list_entry()
            email_outbox_count += 1
            self.check_entry_user_and_timer_start_date_and_email_count(
                user3_wait_list_entry, user3, time_of_user1_exit, email_outbox_count
            )

            # After time_to_expiration minutes
            run_time_service_as(time_of_user1_exit + timezone.timedelta(minutes=time_to_expiration))

            # Expect user3 to be removed from the wait list (EXPIRED=TRUE)
            self.check_entry_has_expired(tool, user3_wait_list_entry, 0)

        finally:
            setup_configuration(time_to_expiration_saved, reservation_buffer_saved)

    def enter_wait_list_mode_fail(self, url, mode, kiosk=False):
        user, project = create_user_and_project(True, True)
        tool = create_tool("WaitList Test Tool", mode)
        usage = create_usage(user, project, tool, timezone.now() - timezone.timedelta(minutes=10), None)
        login_as(self.client, user)
        response = self.client.post(
            url,
            {"tool_id": tool.id, "customer_id": user.id},
            follow=True,
        )
        self.assertContains(response, "does not operate in wait list mode", status_code=200 if kiosk else 400)
        self.assertEqual(tool.current_wait_list().count(), 0)

    def enter_wait_list_mode_pass(self, url, mode):
        user, project = create_user_and_project(True, True)
        tool = create_tool("WaitList Test Tool", mode)
        usage = create_usage(user, project, tool, timezone.now() - timezone.timedelta(minutes=10), None)
        login_as(self.client, user)
        response = self.client.post(
            url,
            {"tool_id": tool.id, "customer_id": user.id},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(tool.current_wait_list().count(), 1)
        self.assertEqual(tool.top_wait_list_entry().user, user)

    def user_enter_wait_list_twice(self, url, kiosk=False):
        user, project = create_user_and_project(True, True)
        tool = create_tool("WaitList Test Tool", Tool.OperationMode.WAIT_LIST)
        usage = create_usage(user, project, tool, timezone.now() - timezone.timedelta(minutes=10), None)
        login_as(self.client, user)
        response = self.client.post(
            url,
            {"tool_id": tool.id, "customer_id": user.id},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(tool.current_wait_list().count(), 1)
        self.assertEqual(tool.top_wait_list_entry().user, user)

        response = self.client.post(
            url,
            {"tool_id": tool.id, "customer_id": user.id},
            follow=True,
        )
        self.assertContains(response, "already in the wait list", status_code=200 if kiosk else 400)
        self.assertEqual(tool.current_wait_list().count(), 1)
        self.assertEqual(tool.top_wait_list_entry().user, user)

    def exit_wait_list_pass(self, enter_url, exit_url):
        user, project = create_user_and_project(True, True)
        tool = create_tool("WaitList Test Tool", Tool.OperationMode.WAIT_LIST)
        usage = create_usage(user, project, tool, timezone.now() - timezone.timedelta(minutes=10), None)
        login_as(self.client, user)
        response = self.client.post(
            enter_url,
            {"tool_id": tool.id, "customer_id": user.id},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(tool.current_wait_list().count(), 1)
        self.assertEqual(tool.top_wait_list_entry().user, user)
        response = self.client.post(
            exit_url,
            {"tool_id": tool.id, "customer_id": user.id},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(tool.current_wait_list().count(), 0)

    def exit_wait_list_not_in_wait_list(self, url, kiosk=False):
        user, project = create_user_and_project(True, True)
        tool = create_tool("WaitList Test Tool", Tool.OperationMode.WAIT_LIST)
        login_as(self.client, user)
        response = self.client.post(
            url,
            {"tool_id": tool.id, "customer_id": user.id},
            follow=True,
        )
        self.assertContains(response, "not in the wait list", status_code=200 if kiosk else 400)
        self.assertEqual(tool.current_wait_list().count(), 0)


def create_tool(name, mode, missed_threshold=None):
    return Tool.objects.create(
        name="[Test Tool] " + name,
        _operation_mode=mode,
        _missed_reservation_threshold=missed_threshold,
    )


def create_usage(user, project, tool, start, end=None):
    return UsageEvent.objects.create(
        user=user,
        operator=user,
        project=project,
        tool=tool,
        start=start,
        end=end,
    )


def create_user(is_facility_manager=False):
    count = User.objects.count()
    return User.objects.create(
        first_name="Testy",
        last_name="McTester",
        username=f"test{count}",
        email=f"test{count}@test.com",
        is_facility_manager=is_facility_manager,
    )


def create_reservation(user, tool, start, end):
    return Reservation.objects.create(
        tool=tool,
        start=start,
        end=end,
        creator=user,
        user=user,
        short_notice=False,
    )


def end_usage(usage, time):
    usage.end = time
    usage.save()
    return time


def run_time_service_as(time):
    do_check_and_update_wait_list(time)
    return time


def setup_configuration(time_to_expiration, reservation_buffer):
    ToolCustomization.set("tool_wait_list_spot_expiration", time_to_expiration)
    ToolCustomization.set("tool_wait_list_reservation_buffer", reservation_buffer)
    return time_to_expiration, reservation_buffer


def get_configuration():
    time_to_expiration = ToolCustomization.get("tool_wait_list_spot_expiration")
    reservation_buffer = ToolCustomization.get("tool_wait_list_reservation_buffer")
    return time_to_expiration, reservation_buffer
