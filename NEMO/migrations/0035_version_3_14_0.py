import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

from NEMO.migrations_utils import create_news_for_version


class Migration(migrations.Migration):

    dependencies = [
        ('NEMO', '0034_version_3_13_0'),
    ]

    def new_version_news(apps, schema_editor):
        create_news_for_version(apps, "3.14.0")

    operations = [
        migrations.RunPython(new_version_news),
        migrations.CreateModel(
            name='TemporaryPhysicalAccess',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('start_time', models.DateTimeField(help_text='The start of the temporary access')),
                ('end_time', models.DateTimeField(help_text='The end of the temporary access')),
                ('physical_access_level', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='NEMO.PhysicalAccessLevel')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-end_time']},
        ),
    ]
