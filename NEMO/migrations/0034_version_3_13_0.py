from django.db import migrations

from NEMO.migrations_utils import create_news_for_version


class Migration(migrations.Migration):

    dependencies = [
        ('NEMO', '0033_version_3_12_0'),
    ]

    def new_version_news(apps, schema_editor):
        create_news_for_version(apps, "3.13.0")

    operations = [
        migrations.RunPython(new_version_news),
    ]
