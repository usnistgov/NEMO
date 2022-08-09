# Generated by Django 3.2.13 on 2022-06-15 19:37

from django.db import migrations

from NEMO.migrations_utils import create_news_for_version


class Migration(migrations.Migration):

    dependencies = [
        ('NEMO', '0039_version_4_1_0'),
    ]

    def new_version_news(apps, schema_editor):
        create_news_for_version(apps, "4.2.0", "")

    operations = [
        migrations.RunPython(new_version_news),
    ]