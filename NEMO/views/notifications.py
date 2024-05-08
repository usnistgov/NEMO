from datetime import datetime, timedelta
from typing import Iterable, List, Set

from django.contrib.contenttypes.models import ContentType
from django.db.models import Count
from django.utils import timezone

from NEMO.models import (
    AdjustmentRequest,
    BuddyRequest,
    Notification,
    RequestMessage,
    StaffAssistanceRequest,
    TemporaryPhysicalAccessRequest,
    User,
)
from NEMO.utilities import end_of_the_day


def delete_expired_notifications():
    Notification.objects.filter(expiration__lt=timezone.now()).delete()


def get_notifications(user: User, notification_type: str, delete=True):
    notifications = Notification.objects.filter(user=user, notification_type=notification_type)
    if notifications:
        notification_ids = list(notifications.values_list("object_id", flat=True))
        if delete:
            notifications.delete()
        return notification_ids
    else:
        return None


def get_notification_counts(user: User):
    notifications = Notification.objects.filter(user=user)
    counts = notifications.values("notification_type").annotate(total=Count("notification_type"))
    return {item["notification_type"]: item["total"] for item in counts}


def delete_notification(notification_type: str, instance_id, users: Iterable[User] = None):
    notifications = Notification.objects.filter(notification_type=notification_type, object_id=instance_id)
    if users:
        notifications = notifications.filter(user__in=users)
    notifications.delete()


def create_news_notification(story):
    # Delete all existing notifications for this story, so we don't have multiple notifications for the same story
    Notification.objects.filter(notification_type=Notification.Types.NEWS, object_id=story.id).delete()
    users = User.objects.filter(is_active=True)
    expiration = timezone.now() + timedelta(days=30)  # Unread news story notifications always expire after 30 days
    for u in users:
        Notification.objects.create(
            user=u, expiration=expiration, content_object=story, notification_type=Notification.Types.NEWS
        )


def create_safety_notification(safety_issue):
    users = User.objects.filter(is_staff=True, is_active=True)
    expiration = timezone.now() + timedelta(days=30)  # Unread safety issue notifications always expire after 30 days
    for u in users:
        Notification.objects.update_or_create(
            user=u,
            notification_type=Notification.Types.SAFETY,
            content_type=ContentType.objects.get_for_model(safety_issue),
            object_id=safety_issue.id,
            defaults={"expiration": expiration},
        )


def create_buddy_request_notification(buddy_request: BuddyRequest):
    users: List[User] = User.objects.filter(is_active=True).exclude(id=buddy_request.user_id)
    request_end = buddy_request.end
    # Unread buddy request notifications expire after the request ends
    expiration = end_of_the_day(datetime(request_end.year, request_end.month, request_end.day))
    for u in users:
        if u.get_preferences().display_new_buddy_request_notification:
            Notification.objects.update_or_create(
                user=u,
                notification_type=Notification.Types.BUDDY_REQUEST,
                content_type=ContentType.objects.get_for_model(buddy_request),
                object_id=buddy_request.id,
                defaults={"expiration": expiration},
            )


def create_staff_assistance_request_notification(staff_assistance_request: StaffAssistanceRequest):
    users: List[User] = User.objects.filter(is_active=True).exclude(id=staff_assistance_request.user_id)
    created_at = staff_assistance_request.creation_time
    expiration = end_of_the_day(datetime(created_at.year, created_at.month, created_at.day))
    for u in users:
        if u.get_preferences().display_new_buddy_request_notification:
            Notification.objects.update_or_create(
                user=u,
                notification_type=Notification.Types.STAFF_ASSISTANCE_REQUEST,
                content_type=ContentType.objects.get_for_model(staff_assistance_request),
                object_id=staff_assistance_request.id,
                defaults={"expiration": expiration},
            )


def create_request_message_notification(reply: RequestMessage, notification_type: str, expiration: datetime):
    for user in reply.content_object.creator_and_reply_users():
        if user != reply.author:
            Notification.objects.update_or_create(
                user=user,
                notification_type=notification_type,
                content_type=ContentType.objects.get_for_model(reply),
                object_id=reply.id,
                defaults={"expiration": expiration},
            )


def create_access_request_notification(access_request: TemporaryPhysicalAccessRequest):
    request_end = access_request.end_time
    expiration = end_of_the_day(datetime(request_end.year, request_end.month, request_end.day))

    users_to_notify: Set[User] = set(access_request.other_users.all())
    users_to_notify.update(access_request.reviewers())
    if access_request.last_updated_by and access_request.last_updated_by != access_request.creator:
        users_to_notify.add(access_request.creator)
    for user in users_to_notify:
        Notification.objects.update_or_create(
            user=user,
            notification_type=Notification.Types.TEMPORARY_ACCESS_REQUEST,
            content_type=ContentType.objects.get_for_model(access_request),
            object_id=access_request.id,
            defaults={"expiration": expiration},
        )


def create_adjustment_request_notification(adjustment_request: AdjustmentRequest):
    users_to_notify = set(adjustment_request.reviewers())
    users_to_notify.add(adjustment_request.creator)
    expiration = timezone.now() + timedelta(days=30)  # 30 days for adjustment requests to expire
    for user in users_to_notify:
        # Only update users other than the one who last updated it
        if not adjustment_request.last_updated_by or adjustment_request.last_updated_by != user:
            Notification.objects.get_or_create(
                user=user,
                notification_type=Notification.Types.ADJUSTMENT_REQUEST,
                content_type=ContentType.objects.get_for_model(adjustment_request),
                object_id=adjustment_request.id,
                defaults={"expiration": expiration},
            )
