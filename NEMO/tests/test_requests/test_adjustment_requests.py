from datetime import timedelta

from django.core.exceptions import NON_FIELD_ERRORS
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
from NEMO.tests.test_utilities import (
    create_user_and_project,
    login_as,
    login_as_staff,
    login_as_user,
    validate_model_error,
)
from NEMO.views.customization import UserRequestsCustomization


class AdjustmentRequestTestCase(TestCase):
    def setUp(self) -> None:
        UserRequestsCustomization.set("adjustment_requests_enabled", "enabled")

    def test_enable_adjustment_requests(self):
        UserRequestsCustomization.set("adjustment_requests_enabled", "")
        login_as_user(self.client)
        response = self.client.get(reverse("adjustment_requests"))
        self.assertContains(response, "not enabled", status_code=400)

    def test_create_request(self):
        user, project = create_user_and_project()
        adjustment_request = AdjustmentRequest()
        validate_model_error(self, adjustment_request, ["creator", "description"])
        adjustment_request.creator = user
        # need a description
        adjustment_request.description = "some description"
        adjustment_request.full_clean()
        adjustment_request.description = ""
        validate_model_error(self, adjustment_request, ["description"])
        adjustment_request.description = "some description"
        # now try with a charge
        start = timezone.now() - timedelta(hours=1)
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
        validate_model_error(self, adjustment_request, [NON_FIELD_ERRORS])
        adjustment_request.new_start = usage_event.start - timedelta(minutes=5)
        adjustment_request.full_clean()
        adjustment_request.save()
        self.assertEqual(adjustment_request.status, RequestStatus.PENDING)

    def test_notification_created(self):
        # Test that new adjustment request => reviewers are notified (here just managers)
        reviewer = User.objects.create(
            username="test_manager", first_name="Managy", last_name="McManager", is_facility_manager=True
        )
        login_as_user(self.client)
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
        login_as_user(self.client)
        response = self.client.get(reverse("delete_adjustment_request", args=[adjustment_request.id]))
        # different user cannot delete
        self.assertContains(response, "You are not allowed to delete a request you", status_code=400)
        login_as(self.client, user)
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
        login_as(self.client, user)
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
        login_as_user(self.client)
        data = {"description": adjustment_request.description}
        if approve_request:
            data["approve_request"] = approve_request
        if deny_request:
            data["deny_request"] = deny_request
        response = self.client.post(reverse("edit_adjustment_request", args=[adjustment_request.id]), data=data)
        # regular user cannot edit request they didn't create
        self.assertContains(response, "You are not allowed to edit this request.")
        staff = login_as_staff(self.client)
        response = self.client.post(reverse("edit_adjustment_request", args=[adjustment_request.id]), data=data)
        # regular staff cannot either
        self.assertContains(response, "You are not allowed to edit this request.")
        # reviewer can
        login_as(self.client, reviewer)
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
        login_as_user(self.client)
        data = {"reply_content": "this is a reply"}
        response = self.client.post(reverse("adjustment_request_reply", args=[adjustment_request.id]), data=data)
        self.assertContains(
            response, "Only the creator and reviewers can reply to adjustment requests", status_code=400
        )
        staff = login_as_staff(self.client)
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
