from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from django.utils.formats import date_format


def migration_format_datetime(universal_time):
    return date_format(timezone.localtime(universal_time), "DATETIME_FORMAT")


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
            content += "\n" + extra_content + "\n"
        content += (
            f"\nClick on the following links to consult the <a href='https://github.com/usnistgov/NEMO/releases/tag/{version}' target='_blank'>NEMO {version} Release Notes</a> "
            f"and the <a href='https://nemo.nist.gov/public/NEMO_Feature_Manual.pdf' target='_blank'>NEMO {version} Feature manual</a>"
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
            notification = Notification(
                user=u,
                expiration=expiration,
                content_type=news_content_type,
                object_id=story.id,
            )
            # This cannot be added directly because it didn't exist prior to 4.5.0
            # and this code is used by ALL migrations, so anyone migrating before
            # (4.2.0 to 4.3.0 for example) would get an exception and get completely stuck.
            notification.notification_type = "news"
            notification.save()


def news_for_version_forward(version):
    def new_version_news(apps, schema_editor):
        create_news_for_version(apps, version, "")

    return new_version_news


def news_for_version_reverse(version):
    def new_version_news(apps, schema_editor):
        News = apps.get_model("NEMO", "News")
        News.objects.filter(title=f"What's new in NEMO {version}?").delete()

    return new_version_news
