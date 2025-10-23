from calendar import monthrange
from datetime import datetime

from dateutil.relativedelta import relativedelta
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from NEMO.models import (
    AdjustmentRequest,
    Notification,
    RequestMessage,
    RequestStatus,
    Tool,
    UsageEvent,
    User,
)
from NEMO.tests.test_utilities import NEMOTestCaseMixin, create_user_and_project
from NEMO.utilities import RecurrenceFrequency, beginning_of_next_day, beginning_of_the_day
from NEMO.views.customization import AdjustmentRequestsCustomization


class AdjustmentRequestTestCase(NEMOTestCaseMixin, TestCase):
    def setUp(self) -> None:
        AdjustmentRequestsCustomization.set("adjustment_requests_enabled", "enabled")

    def test_enable_adjustment_requests(self):
        AdjustmentRequestsCustomization.set("adjustment_requests_enabled", "")
        self.login_as_user()
        response = self.client.get(reverse("adjustment_requests", args=[0]))
        self.assertContains(response, "not enabled", status_code=400)

    def test_enable_adjustment_requests_reviewers_only(self):
        AdjustmentRequestsCustomization.set("adjustment_requests_enabled", "reviewers_only")
        self.login_as_user()
        response = self.client.get(reverse("adjustment_requests", args=[0]))
        self.assertContains(response, "not enabled", status_code=400)
        tool = Tool.objects.create(name="tool")
        user = User.objects.create(username="test", first_name="t", last_name="e")
        tool.adjustment_request_reviewers.add(user)
        self.login_as(user)
        response = self.client.get(reverse("adjustment_requests", args=[0]))
        self.assertTrue(response.status_code == 200)

    def test_create_request(self):
        user, project = create_user_and_project()
        adjustment_request = AdjustmentRequest()
        self.validate_model_error(adjustment_request, ["creator", "description"])
        adjustment_request.creator = user
        # need a description
        adjustment_request.description = "some description"
        adjustment_request.full_clean()
        adjustment_request.description = ""
        self.validate_model_error(adjustment_request, ["description"])
        adjustment_request.description = "some description"
        # now try with a charge
        start = timezone.now() - relativedelta(hours=1)
        usage_event = UsageEvent.objects.create(
            user=user,
            operator=user,
            project=project,
            tool=Tool.objects.create(name="tool"),
            start=start,
            end=timezone.now(),
        )
        adjustment_request.item = usage_event
        adjustment_request.new_start = usage_event.start
        adjustment_request.new_end = usage_event.end
        adjustment_request.new_start = usage_event.start - relativedelta(minutes=5)
        adjustment_request.full_clean()
        adjustment_request.save()
        self.assertEqual(adjustment_request.status, RequestStatus.PENDING)

    def test_notification_created(self):
        # Test that new adjustment request => reviewers are notified (here just managers)
        reviewer = User.objects.create(
            username="test_manager", first_name="Managy", last_name="McManager", is_facility_manager=True
        )
        self.login_as_user()
        data = {
            "description": "some adjustment request",
        }
        self.client.post(reverse("create_adjustment_request"), data=data)
        self.assertTrue(
            Notification.objects.filter(user=reviewer, notification_type=Notification.Types.ADJUSTMENT_REQUEST).exists()
        )

    def test_delete_request(self):
        user, project = create_user_and_project()
        adjustment_request = AdjustmentRequest()
        adjustment_request.creator = user
        adjustment_request.description = "some adjustment request"
        adjustment_request.save()
        self.login_as_user()
        response = self.client.get(reverse("delete_adjustment_request", args=[adjustment_request.id]))
        # different user cannot delete
        self.assertContains(response, "You are not allowed to delete a request you", status_code=400)
        self.login_as(user)
        adjustment_request.status = RequestStatus.APPROVED
        adjustment_request.save()
        response = self.client.get(reverse("delete_adjustment_request", args=[adjustment_request.id]))
        # cannot delete non pending request
        self.assertContains(
            response, "You are not allowed to delete a request that was already completed", status_code=400
        )
        adjustment_request.status = RequestStatus.PENDING
        adjustment_request.save()
        response = self.client.get(reverse("delete_adjustment_request", args=[adjustment_request.id]))
        self.assertRedirects(response, reverse("user_requests", args=["adjustment"]))
        self.assertTrue(AdjustmentRequest.objects.get(id=adjustment_request.id).deleted)

    def test_approve_request(self):
        self.review_request(approve_request="Approve")

    def test_deny_request(self):
        self.review_request(deny_request="Deny")

    def review_request(self, approve_request="", deny_request=""):
        reviewer = User.objects.create(username="manager", first_name="", last_name="Manager", is_facility_manager=True)
        user, project = create_user_and_project()
        self.login_as(user)
        data = {
            "description": "some adjustment request",
        }
        self.client.post(reverse("create_adjustment_request"), data=data)
        adjustment_request = AdjustmentRequest.objects.first()
        # Notification exists
        self.assertTrue(
            Notification.objects.filter(
                notification_type=Notification.Types.ADJUSTMENT_REQUEST, object_id=adjustment_request.id
            ).exists()
        )
        self.login_as_user()
        data = {"description": adjustment_request.description}
        if approve_request:
            data["approve_request"] = approve_request
        if deny_request:
            data["deny_request"] = deny_request
        response = self.client.post(reverse("edit_adjustment_request", args=[adjustment_request.id]), data=data)
        # regular user cannot edit request they didn't create
        self.assertContains(response, "You are not allowed to edit this request.")
        staff = self.login_as_staff()
        response = self.client.post(reverse("edit_adjustment_request", args=[adjustment_request.id]), data=data)
        # regular staff cannot either
        self.assertContains(response, "You are not allowed to edit this request.")
        # reviewer can
        self.login_as(reviewer)
        response = self.client.post(reverse("edit_adjustment_request", args=[adjustment_request.id]), data=data)
        self.assertRedirects(response, reverse("user_requests", args=["adjustment"]))
        adjustment_request = AdjustmentRequest.objects.get(id=adjustment_request.id)
        status = RequestStatus.APPROVED if approve_request else RequestStatus.DENIED
        self.assertEqual(adjustment_request.status, status)
        # Notification doesn't exist anymore (for reviewer)
        self.assertFalse(
            Notification.objects.filter(
                user=reviewer, notification_type=Notification.Types.ADJUSTMENT_REQUEST, object_id=adjustment_request.id
            ).exists()
        )

    def test_reply(self):
        user, project = create_user_and_project()
        adjustment_request = AdjustmentRequest()
        adjustment_request.creator = user
        adjustment_request.description = "some adjustment request"
        adjustment_request.save()
        self.login_as_user()
        data = {"reply_content": "this is a reply"}
        response = self.client.post(reverse("adjustment_request_reply", args=[adjustment_request.id]), data=data)
        self.assertContains(
            response, "Only the creator and reviewers can reply to adjustment requests", status_code=400
        )
        staff = self.login_as_staff()
        response = self.client.post(reverse("adjustment_request_reply", args=[adjustment_request.id]), data=data)
        self.assertContains(
            response, "Only the creator and reviewers can reply to adjustment requests", status_code=400
        )
        staff.is_facility_manager = True
        staff.save()
        response = self.client.post(reverse("adjustment_request_reply", args=[adjustment_request.id]), data=data)
        self.assertRedirects(response, reverse("user_requests", args=["adjustment"]))
        # check that the message exists and the creator was notified
        self.assertTrue(
            RequestMessage.objects.filter(
                object_id=adjustment_request.id, author=staff, content="this is a reply"
            ).exists()
        )
        self.assertTrue(
            Notification.objects.filter(
                user=user, notification_type=Notification.Types.ADJUSTMENT_REQUEST_REPLY
            ).exists()
        )
        # author doesn't get notification of his own reply
        self.assertFalse(
            Notification.objects.filter(
                user=staff, notification_type=Notification.Types.ADJUSTMENT_REQUEST_REPLY
            ).exists()
        )
        # now creator replies too
        self.client.post(
            reverse("adjustment_request_reply", args=[adjustment_request.id]), data={"reply_content": "another reply"}
        )
        self.assertTrue(
            Notification.objects.filter(
                user=user, notification_type=Notification.Types.ADJUSTMENT_REQUEST_REPLY
            ).exists()
        )
        # Cannot reply if the request is already completed
        adjustment_request.status = RequestStatus.APPROVED
        adjustment_request.save()
        response = self.client.post(
            reverse("adjustment_request_reply", args=[adjustment_request.id]), data={"reply_content": "another one"}
        )
        self.assertContains(response, "Replies are only allowed on PENDING requests", status_code=400)

    def test_date_limit(self):
        # 20 days window
        today = timezone.localtime()
        self.assertEqual(
            beginning_of_next_day(today - relativedelta(days=20)),
            test_date_limit_dates("", str(RecurrenceFrequency.DAILY.index), "20"),
        )
        # 1 month window
        self.assertEqual(
            beginning_of_next_day(today - relativedelta(months=1)),
            test_date_limit_dates("", str(RecurrenceFrequency.MONTHLY.index), "1"),
        )
        # billing cycle today, cutoff is the first of last month
        self.assertEqual(
            beginning_of_the_day((today - relativedelta(months=1)).replace(day=1)), test_date_limit_dates(today.day)
        )
        if today.day != monthrange(today.year, today.month)[1]:
            # if we are not the last day of the month
            # set billing day as tomorrow, so we are before it. in that case cutoff should be 1 of last month
            self.assertEqual(
                beginning_of_the_day((today - relativedelta(months=1)).replace(day=1)),
                test_date_limit_dates(today.day + 1),
            )
            # test with also a period cutoff of 1 day, which should take precedence
            self.assertEqual(
                beginning_of_the_day(today),
                test_date_limit_dates(today.day + 1, str(RecurrenceFrequency.DAILY.index), "1"),
            )
        if today.day != monthrange(today.year, today.month)[0]:
            # if we are not the first day of the month
            # set billing day as yesterday, so we are after it. in that case cutoff should be 1 of this month
            self.assertEqual(beginning_of_the_day(today.replace(day=1)), test_date_limit_dates(today.day - 1))
            # test with also a period cutoff of 1 day, which should take precedence
            self.assertEqual(
                beginning_of_the_day(today),
                test_date_limit_dates(today.day - 1, str(RecurrenceFrequency.DAILY.index), "1"),
            )


def test_date_limit_dates(billing_days, freq="", interval="") -> datetime:
    AdjustmentRequestsCustomization.set("adjustment_requests_time_limit_monthly_cycle_day", billing_days)
    AdjustmentRequestsCustomization.set("adjustment_requests_time_limit_frequency", freq)
    AdjustmentRequestsCustomization.set("adjustment_requests_time_limit_interval", interval)
    return AdjustmentRequestsCustomization.get_date_limit()
