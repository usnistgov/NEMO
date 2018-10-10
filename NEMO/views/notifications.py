from datetime import timedelta

from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from NEMO.models import News, Notification, SafetyIssue, User


def delete_expired_notifications():
	Notification.objects.filter(expiration__lt=timezone.now()).delete()


def get_notifications(user, notification_type):
	content_type = ContentType.objects.get_for_model(notification_type)
	notifications = Notification.objects.filter(user=user, content_type=content_type)
	if notifications:
		notification_ids = list(notifications.values_list('object_id', flat=True))
		notifications.delete()
		return notification_ids
	else:
		return None


def get_notificaiton_counts(user):
	counts = {}
	for t in Notification.Types.Choices:
		model = t[0]
		content_type = ContentType.objects.get(app_label='NEMO', model=model)
		counts[model] = Notification.objects.filter(user=user, content_type=content_type).count()
	return counts


def create_news_notification(story):
	content_type = ContentType.objects.get_for_model(News)
	Notification.objects.filter(content_type=content_type, object_id=story.id).delete()  # Delete all existing notifications for this story, so we don't have multiple notifications for the same story
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
