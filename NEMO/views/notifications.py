from datetime import timedelta, datetime
from typing import Type, List

from django.contrib.contenttypes.models import ContentType
from django.db.models import Model
from django.utils import timezone

from NEMO.models import News, Notification, SafetyIssue, User, BuddyRequest, BuddyRequestMessage
from NEMO.utilities import end_of_the_day


def delete_expired_notifications():
	Notification.objects.filter(expiration__lt=timezone.now()).delete()


def get_notifications(user: User, notification_type: Type[Model]):
	content_type = ContentType.objects.get_for_model(notification_type)
	notifications = Notification.objects.filter(user=user, content_type=content_type)
	if notifications:
		notification_ids = list(notifications.values_list("object_id", flat=True))
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


def create_news_notification(story):
	content_type = ContentType.objects.get_for_model(News)
	# Delete all existing notifications for this story, so we don't have multiple notifications for the same story
	Notification.objects.filter(
		content_type=content_type, object_id=story.id
	).delete()
	users = User.objects.filter(is_active=True)
	expiration = timezone.now() + timedelta(days=30)  # Unread news story notifications always expire after 30 days
	for u in users:
		Notification.objects.create(user=u, expiration=expiration, content_object=story)


def delete_news_notification(story):
	content_type = ContentType.objects.get_for_model(News)
	Notification.objects.filter(content_type=content_type, object_id=story.id).delete()


def create_safety_notification(safety_issue):
	users = User.objects.filter(is_staff=True, is_active=True)
	expiration = timezone.now() + timedelta(days=30)  # Unread safety issue notifications always expire after 30 days
	for u in users:
		Notification.objects.create(user=u, expiration=expiration, content_object=safety_issue)


def delete_safety_notification(issue):
	content_type = ContentType.objects.get_for_model(SafetyIssue)
	Notification.objects.filter(content_type=content_type, object_id=issue.id).delete()


def create_buddy_request_notification(buddy_request: BuddyRequest):
	users: List[User] = User.objects.filter(is_active=True).exclude(id=buddy_request.user_id)
	request_end = buddy_request.end
	# Unread buddy request notifications expire after the request ends
	expiration = end_of_the_day(
		datetime(request_end.year, request_end.month, request_end.day)
	)
	for u in users:
		if u.get_preferences().display_new_buddy_request_notification:
			Notification.objects.create(user=u, expiration=expiration, content_object=buddy_request)


def delete_buddy_request_notification(buddy_request: BuddyRequest):
	content_type = ContentType.objects.get_for_model(BuddyRequest)
	Notification.objects.filter(content_type=content_type, object_id=buddy_request.id).delete()


def create_buddy_reply_notification(reply: BuddyRequestMessage):
	creator: User = reply.buddy_request.user
	request_end = reply.buddy_request.end
	# Unread buddy request reply notifications expire after the request ends
	expiration = end_of_the_day(
		datetime(request_end.year, request_end.month, request_end.day)
	)
	for user in reply.buddy_request.creator_and_reply_users():
		if user != reply.author and (
				user == creator or user.get_preferences().display_new_buddy_request_reply_notification
		):
			Notification.objects.create(user=user, expiration=expiration, content_object=reply)
