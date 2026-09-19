from django.db import migrations

# Maps each email template name to a Django template string reproducing, as closely as possible, what the
# hardcoded Python code currently computes as that email's subject line. Written once as real starting values
# instead of the implicit "{{ default_subject }}" passthrough, so an admin visiting the customization page sees
# the actual current subject (with its variables and branching spelled out) rather than an opaque placeholder.
#
# "generic_email" (the broadcast email) is intentionally excluded. Its subject is typed fresh by the sender on
# every send, so there is no fixed "current default" to backfill.
#
# From/cc are intentionally left untouched everywhere, as none of these 28 templates branch on from/cc, so a
# backfilled value there would be identical to the passthrough default already in effect.
SUBJECT_TEMPLATES = {
    "unauthorized_tool_access_email": (
        '{% if type == "area-access" %}Area access requirement{% else %}Area reservation requirement{% endif %}'
    ),
    "access_request_notification_email": (
        '{% if status == "received" or status == "updated" %}'
        "Access request for the {{ access_request.physical_access_level.area }} {{ status }}"
        "{% else %}"
        "Your access request for the {{ access_request.physical_access_level.area }} has been {{ status }}"
        "{% endif %}"
    ),
    "adjustment_request_notification_email": (
        '{% if status == "received" or status == "updated" %}'
        "Adjustment request {{ status }}"
        "{% elif user_office %}"
        "{{ adjustment_request.creator.get_name }}'s adjustment request has been {{ status }}"
        "{% else %}"
        "Your adjustment request has been {{ status }}"
        "{% endif %}"
    ),
    "cancellation_email": "Your reservation was cancelled",
    "counter_threshold_reached_email": "Warning threshold reached for {{ counter.tool.name }} {{ counter.name }} counter",
    "facility_rules_tutorial_email": "{{ facility_name }} rules tutorial",
    "feedback_email": "Feedback from {{ user }}",
    "missed_reservation_email": "Missed reservation for the {{ reservation.reservation_item }}",
    "new_task_email": (
        "{% if task.safety_hazard %}SAFETY HAZARD: {% endif %}"
        "{{ task.tool.name }}"
        "{% if task.force_shutdown %} shutdown{% else %} problem{% endif %}"
    ),
    "out_of_time_reservation_email": (
        "{% if reservation.start %}"
        "Out of time for the {{ reservation.reservation_item }}"
        "{% else %}"
        "Out of allowed schedule for the {{ reservation.reservation_item }}"
        "{% endif %}"
    ),
    "recurring_charges_reminder_email": "{{ recurring_charges_name }} will be charged in {{ reminder_days }} day(s)",
    "reorder_supplies_reminder_email": "Time to order more {{ item.name }}",
    "reservation_ending_reminder_email": "{{ reservation.reservation_item.name }} reservation ending soon",
    "reservation_reminder_email": "{{ reservation.reservation_item.name }} reservation reminder",
    "reservation_warning_email": (
        "{{ reservation.reservation_item.name }} reservation {% if fatal_error %}problem{% else %}warning{% endif %}"
    ),
    "safety_issue_email": "Safety issue",
    "scheduled_outage_reminder_email": "{{ outage.title }} reminder",
    "staff_charge_reminder_email": 'Active staff charge since {{ staff_charge.start|date:"DATETIME_FORMAT" }}',
    "task_status_notification": "{{ task.tool }} task notification",
    "tool_qualification_expiration_email": (
        "Your {{ tool.name }} qualification "
        "{% if remaining_days %} expires in {{ remaining_days }} days!{% else %} has expired{% endif %}"
    ),
    "tool_required_unanswered_questions_email": (
        "Unanswered post‑usage questions after logoff from the {{ tool.name }}"
    ),
    "usage_reminder_email": "{{ facility_name }} usage",
    "user_access_expiration_reminder_email": (
        "Your {{ facility_name }} access expires in {{ remaining_days }} days "
        '({{ user.access_expiration|date:"DATE_FORMAT" }})'
    ),
    "reservation_created_user_email": "Reservation for the {{ reservation.reservation_item }}",
    "reservation_cancelled_user_email": "Cancelled Reservation for the {{ reservation.reservation_item }}",
    "weekend_access_email": (
        "{% if not weekend_access %}NO w{% else %}W{% endif %}eekend access for the "
        "{{ facility_name }} {{ sat }} - {{ sun }}"
    ),
    "wait_list_notification_email": "Your turn for the {{ tool }}",
}


def backfill_email_subjects(apps, schema_editor):
    # Only skip a row if it holds a value other than the plain "{{ default_subject }}" passthrough: a row
    # that's missing entirely, or one that's present but still exactly the passthrough placeholder, both mean
    # "not really customized" (the passthrough placeholder was, until this migration, the only value the
    # customization page's field could ever show, and can end up saved as a real row if the shared form was
    # ever submitted without editing that field) - safe to fill in with the real subject in both cases. Any
    # other existing value is a genuine admin customization and must be left alone.
    Customization = apps.get_model("NEMO", "Customization")
    for template_name, subject_template in SUBJECT_TEMPLATES.items():
        name = f"{template_name}_subject"
        existing = Customization.objects.filter(name=name).first()
        if existing is None:
            Customization.objects.create(name=name, value=subject_template)
        elif existing.value == "{{ default_subject }}":
            existing.value = subject_template
            existing.save(update_fields=["value"])


def remove_backfilled_email_subjects(apps, schema_editor):
    # Only remove rows that still hold exactly the value this migration wrote - if an admin has since edited
    # one of these fields to something else, that's their real customization and reversing must not delete it.
    Customization = apps.get_model("NEMO", "Customization")
    for template_name, subject_template in SUBJECT_TEMPLATES.items():
        Customization.objects.filter(name=f"{template_name}_subject", value=subject_template).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("NEMO", "0157_task_assigned_to"),
    ]

    operations = [
        migrations.RunPython(backfill_email_subjects, remove_backfilled_email_subjects),
    ]
