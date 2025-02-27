# Generated by Django 4.2.15 on 2024-09-29 19:01

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("NEMO", "0090_toolusagecounter_counter_direction_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="adjustmentrequest",
            name="waive",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="areaaccessrecord",
            name="waived",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="areaaccessrecord",
            name="waived_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="area_access_waived_set",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="areaaccessrecord",
            name="waived_on",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="consumablewithdraw",
            name="waived",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="consumablewithdraw",
            name="waived_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="consumable_withdrawal_waived_set",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="consumablewithdraw",
            name="waived_on",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="reservation",
            name="waived",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="reservation",
            name="waived_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="reservation_waived_set",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="reservation",
            name="waived_on",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="staffcharge",
            name="waived",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="staffcharge",
            name="waived_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="staff_charge_waived_set",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="staffcharge",
            name="waived_on",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="trainingsession",
            name="waived",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="trainingsession",
            name="waived_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="training_waived_set",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="trainingsession",
            name="waived_on",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="usageevent",
            name="waived",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="usageevent",
            name="waived_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="usage_event_waived_set",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="usageevent",
            name="waived_on",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
