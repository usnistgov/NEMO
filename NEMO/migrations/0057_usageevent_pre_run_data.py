# Generated by Django 3.2.22 on 2024-01-10 14:47

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('NEMO', '0056_tool__pre_usage_questions'),
    ]

    operations = [
        migrations.AddField(
            model_name='usageevent',
            name='pre_run_data',
            field=models.TextField(blank=True, null=True),
        ),
    ]
