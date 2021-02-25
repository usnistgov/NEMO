from datetime import timedelta

from django.conf import settings
from django.utils import timezone


def migration_format_datetime(universal_time):
    local_time = universal_time.astimezone(timezone.get_current_timezone())
    day = int(local_time.strftime("%d"))
    if 4 <= day <= 20 or 24 <= day <= 30:
        suffix = "th"
    else:
        suffix = ["st", "nd", "rd"][day % 10 - 1]
    return (
        local_time.strftime("%A, %B ")
        + str(day)
        + suffix
        + local_time.strftime(", %Y @ ")
        + local_time.strftime("%I:%M %p").lstrip("0")
    )


def create_news_for_version(apps, version, extra_content=None):
    if getattr(settings, "NEW_VERSION_NEWS", True):
        News = apps.get_model("NEMO", "News")
        Notification = apps.get_model("NEMO", "Notification")
        User = apps.get_model("NEMO", "User")
        news_content_type = apps.get_model("contenttypes", "ContentType").objects.get_for_model(News)
        now = timezone.now()
        story = News()
        story.title = f"What's new in NEMO {version}?"
        content = f"Thank you for updating to NEMO {version}.\n"
        if extra_content:
            content += extra_content + "\n"
        content += (
            f"\nClick on the following links to consult the <a href='https://github.com/usnistgov/NEMO/releases/tag/{version}' target='_blank'>Release Notes</a> "
            f"and the <a href='https://github.com/usnistgov/NEMO/raw/{version}/documentation/NEMO_Feature_Manual.pdf' target='_blank'>Feature manual</a>"
        )
        content = f"Originally published on {migration_format_datetime(now)} by NEMO:\n" + content.strip()
        story.original_content = content
        story.created = now
        story.all_content = content
        story.last_updated = now
        story.last_update_content = content
        story.update_count = 0
        story.save()
        users = User.objects.filter(is_active=True)
        expiration = now + timedelta(days=30)  # Unread news story notifications always expire after 30 days
        for u in users:
            Notification.objects.create(
                user=u, expiration=expiration, content_type=news_content_type, object_id=story.id
            )
