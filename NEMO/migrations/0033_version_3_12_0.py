from django.db import migrations, models

from NEMO.migrations_utils import create_news_for_version


class Migration(migrations.Migration):

    dependencies = [
        ('NEMO', '0032_version_3_11_0'),
    ]

    def new_version_news(apps, schema_editor):
        create_news_for_version(apps, "3.12.0")

    operations = [
        migrations.RunPython(new_version_news),
    ]
