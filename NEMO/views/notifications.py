from datetime import datetime, timedelta
from typing import List, Set, Type

from django.contrib.contenttypes.models import ContentType
from django.db.models import Model
from django.utils import timezone

from NEMO.models import BuddyRequest, BuddyRequestMessage, News, Notification, TemporaryPhysicalAccessRequest, User
from NEMO.utilities import end_of_the_day


def delete_expired_notifications():
	Notification.objects.filter(expiration__lt=timezone.now()).delete()


def get_notifications(user: User, notification_type: Type[Model], delete=True):
	content_type = ContentType.objects.get_for_model(notification_type)
	notifications = Notification.objects.filter(user=user, content_type=content_type)
	if notifications:
		notification_ids = list(notifications.values_list("object_id", flat=True))
		if delete:
			notifications.delete()
		return notification_ids
	else:
		return None


def get_notification_counts(user: User):
	counts = {}
	for t in Notification.Types.Choices:
		model = t[0]
		content_type = ContentType.objects.get(app_label="NEMO", model=model)
		counts[model] = Notification.objects.filter(user=user, content_type=content_type).count()
	return counts


def delete_notification(notification_type: Type[Model], instance_id, users: List[User] = None):
	content_type = ContentType.objects.get_for_model(notification_type)
	notifications = Notification.objects.filter(content_type=content_type, object_id=instance_id)
	if users:
		notifications = notifications.filter(user__in=users)
	notifications.delete()


def create_news_notification(story):
	content_type = ContentType.objects.get_for_model(News)
	# Delete all existing notifications for this story, so we don't have multiple notifications for the same story
	Notification.objects.filter(content_type=content_type, object_id=story.id).delete()
	users = User.objects.filter(is_active=True)
	expiration = timezone.now() + timedelta(days=30)  # Unread news story notifications always expire after 30 days
	for u in users:
		Notification.objects.create(user=u, expiration=expiration, content_object=story)


def create_safety_notification(safety_issue):
	users = User.objects.filter(is_staff=True, is_active=True)
	expiration = timezone.now() + timedelta(days=30)  # Unread safety issue notifications always expire after 30 days
	for u in users:
		Notification.objects.create(user=u, expiration=expiration, content_object=safety_issue)


def create_buddy_request_notification(buddy_request: BuddyRequest):
	users: List[User] = User.objects.filter(is_active=True).exclude(id=buddy_request.user_id)
	request_end = buddy_request.end
	# Unread buddy request notifications expire after the request ends
	expiration = end_of_the_day(datetime(request_end.year, request_end.month, request_end.day))
	for u in users:
		if u.get_preferences().display_new_buddy_request_notification:
			Notification.objects.create(user=u, expiration=expiration, content_object=buddy_request)


def create_buddy_reply_notification(reply: BuddyRequestMessage):
	creator: User = reply.buddy_request.user
	request_end = reply.buddy_request.end
	# Unread buddy request reply notifications expire after the request ends
	expiration = end_of_the_day(datetime(request_end.year, request_end.month, request_end.day))
	for user in reply.buddy_request.creator_and_reply_users():
		if user != reply.author and (
				user == creator or user.get_preferences().display_new_buddy_request_reply_notification
		):
			Notification.objects.create(user=user, expiration=expiration, content_object=reply)


def create_access_request_notification(access_request: TemporaryPhysicalAccessRequest):
	request_end = access_request.end_time
	expiration = end_of_the_day(datetime(request_end.year, request_end.month, request_end.day))

	reviewers: List[User] = User.objects.filter(is_active=True, is_facility_manager=True)

	users_to_notify: Set[User] = set(access_request.other_users.all())
	users_to_notify.update(reviewers)
	if access_request.last_updated_by and access_request.last_updated_by != access_request.creator:
		users_to_notify.add(access_request.creator)
	for user in users_to_notify:
		Notification.objects.update_or_create(
			user=user,
			content_type=ContentType.objects.get_for_model(access_request),
			object_id=access_request.id,
			defaults={"expiration": expiration}
		)
