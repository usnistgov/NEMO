# Generated by Django 4.2.20 on 2025-03-24 15:57
from django.db import migrations

from NEMO import migrations_utils


class Migration(migrations.Migration):

    dependencies = [
        ("NEMO", "0109_customization_area_logout_already_logged_in_update"),
    ]

    operations = [
        migrations.RunPython(
            migrations_utils.news_for_version_forward("7.1.1"), migrations_utils.news_for_version_reverse("7.1.1")
        ),
    ]
