# Generated by Django 3.2.22 on 2024-01-10 19:19

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("NEMO", "0057_version_5_3_0"),
    ]

    operations = [
        migrations.AddField(
            model_name="userpreferences",
            name="change_reservation_confirmation_override",
            field=models.BooleanField(
                default=False,
                help_text="Override default move/resize reservation confirmation setting",
            ),
        ),
        migrations.AddField(
            model_name="userpreferences",
            name="create_reservation_confirmation_override",
            field=models.BooleanField(
                default=False,
                help_text="Override default create reservation confirmation setting",
            ),
        ),
    ]
