"""
Verifies that every subject template written by the 0158_backfill_email_subject_customizations data migration
renders identically to what the original, hardcoded Python code originally computed for that email's subject,
for every branch of every conditional. This is a content-fidelity check, as the migration must reproduce today's
behavior exactly, not just be "close enough", since a wrong migrated value becomes the live subject for real
emails the moment the migration runs.
"""

import importlib

from django.test import TestCase

from NEMO.tests.test_utilities import NEMOTestCaseMixin
from NEMO.utilities import render_email_template

migration_module = importlib.import_module(
    "NEMO.migrations.0158_backfill_email_subject_customizations"
)
SUBJECT_TEMPLATES = migration_module.SUBJECT_TEMPLATES


class Obj:
    """A minimal stand-in for a model instance: arbitrary attributes, optional custom __str__."""

    def __init__(self, _str=None, **kwargs):
        self.__dict__.update(kwargs)
        self._str = _str

    def __str__(self):
        return self._str if self._str is not None else super().__str__()


class SubjectMigrationFidelityTestCase(NEMOTestCaseMixin, TestCase):
    def render(self, template_name, context):
        return render_email_template(SUBJECT_TEMPLATES[template_name], context)

    def test_unauthorized_tool_access_email(self):
        self.assertEqual(
            self.render("unauthorized_tool_access_email", {"type": "area-access"}), "Area access requirement"
        )
        self.assertEqual(
            self.render("unauthorized_tool_access_email", {"type": "area-reservation"}),
            "Area reservation requirement",
        )

    def test_access_request_notification_email(self):
        area = Obj(_str="Cleanroom")
        access_request = Obj(physical_access_level=Obj(area=area))
        for status in ("received", "updated"):
            expected = f"Access request for the {area} {status}"
            actual = self.render(
                "access_request_notification_email", {"access_request": access_request, "status": status}
            )
            self.assertEqual(actual, expected)
        for status in ("approved", "denied"):
            expected = f"Your access request for the {area} has been {status}"
            actual = self.render(
                "access_request_notification_email", {"access_request": access_request, "status": status}
            )
            self.assertEqual(actual, expected)

    def test_adjustment_request_notification_email(self):
        creator = Obj(get_name=lambda: "Jane Doe")
        adjustment_request = Obj(creator=creator)
        for status in ("received", "updated"):
            expected = f"Adjustment request {status}"
            actual = self.render(
                "adjustment_request_notification_email",
                {"adjustment_request": adjustment_request, "status": status},
            )
            self.assertEqual(actual, expected)
        for status in ("approved", "denied"):
            expected = f"Your adjustment request has been {status}"
            actual = self.render(
                "adjustment_request_notification_email",
                {"adjustment_request": adjustment_request, "status": status},
            )
            self.assertEqual(actual, expected)
        status = "approved"
        expected = f"{creator.get_name()}'s adjustment request has been {status}"
        actual = self.render(
            "adjustment_request_notification_email",
            {"adjustment_request": adjustment_request, "status": status, "user_office": True},
        )
        self.assertEqual(actual, expected)

    def test_cancellation_email(self):
        self.assertEqual(self.render("cancellation_email", {}), "Your reservation was cancelled")

    def test_counter_threshold_reached_email(self):
        counter = Obj(tool=Obj(name="Laser Cutter"), name="Gas level")
        expected = f"Warning threshold reached for {counter.tool.name} {counter.name} counter"
        self.assertEqual(self.render("counter_threshold_reached_email", {"counter": counter}), expected)

    def test_facility_rules_tutorial_email(self):
        facility_name = "NanoFab"
        self.assertEqual(
            self.render("facility_rules_tutorial_email", {"facility_name": facility_name}),
            f"{facility_name} rules tutorial",
        )

    def test_feedback_email(self):
        user = Obj(_str="jsmith")
        self.assertEqual(self.render("feedback_email", {"user": user}), f"Feedback from {user}")

    def test_missed_reservation_email(self):
        reservation = Obj(reservation_item=Obj(_str="Laser Cutter"))
        expected = "Missed reservation for the " + str(reservation.reservation_item)
        self.assertEqual(self.render("missed_reservation_email", {"reservation": reservation}), expected)

    def test_new_task_email(self):
        for safety_hazard in (False, True):
            for force_shutdown in (False, True):
                task = Obj(safety_hazard=safety_hazard, force_shutdown=force_shutdown, tool=Obj(name="SEM"))
                expected = (
                    ("SAFETY HAZARD: " if task.safety_hazard else "")
                    + task.tool.name
                    + (" shutdown" if task.force_shutdown else " problem")
                )
                actual = self.render("new_task_email", {"task": task})
                self.assertEqual(actual, expected)

    def test_out_of_time_reservation_email(self):
        name = "Laser Cutter"
        for has_start in (True, False):
            reservation = Obj(start=has_start, reservation_item=Obj(_str=name))
            expected = "Out of time for the " + name if has_start else "Out of allowed schedule for the " + name
            actual = self.render("out_of_time_reservation_email", {"reservation": reservation})
            self.assertEqual(actual, expected)

    def test_recurring_charges_reminder_email(self):
        recurring_charges_name = "Recurring charges"
        reminder_days = 7
        expected = f"{recurring_charges_name} will be charged in {reminder_days} day(s)"
        actual = self.render(
            "recurring_charges_reminder_email",
            {"recurring_charges_name": recurring_charges_name, "reminder_days": reminder_days},
        )
        self.assertEqual(actual, expected)

    def test_reorder_supplies_reminder_email(self):
        item = Obj(name="Gloves")
        self.assertEqual(
            self.render("reorder_supplies_reminder_email", {"item": item}), f"Time to order more {item.name}"
        )

    def test_reservation_ending_reminder_email(self):
        reservation = Obj(reservation_item=Obj(name="Laser Cutter"))
        expected = reservation.reservation_item.name + " reservation ending soon"
        self.assertEqual(self.render("reservation_ending_reminder_email", {"reservation": reservation}), expected)

    def test_reservation_reminder_email(self):
        item_name = "Laser Cutter"
        reservation = Obj(reservation_item=Obj(name=item_name))
        expected = item_name + " reservation reminder"
        self.assertEqual(self.render("reservation_reminder_email", {"reservation": reservation}), expected)

    def test_reservation_warning_email(self):
        item_name = "Laser Cutter"
        for fatal_error in (True, False):
            reservation = Obj(reservation_item=Obj(name=item_name))
            expected = item_name + (" reservation problem" if fatal_error else " reservation warning")
            actual = self.render(
                "reservation_warning_email", {"reservation": reservation, "fatal_error": fatal_error}
            )
            self.assertEqual(actual, expected)
            # tasks.py's variant reaches the tool via reservation.tool rather than reservation.reservation_item;
            # both must render the same subject through the one shared template.
            reservation_tool_shaped = Obj(reservation_item=Obj(name=item_name), tool=Obj(name=item_name))
            actual_tool_shaped = self.render(
                "reservation_warning_email", {"reservation": reservation_tool_shaped, "fatal_error": fatal_error}
            )
            self.assertEqual(actual_tool_shaped, expected)

    def test_safety_issue_email(self):
        self.assertEqual(self.render("safety_issue_email", {}), "Safety issue")

    def test_scheduled_outage_reminder_email(self):
        outage = Obj(title="Power maintenance")
        self.assertEqual(self.render("scheduled_outage_reminder_email", {"outage": outage}), f"{outage.title} reminder")

    def test_staff_charge_reminder_email(self):
        import datetime

        from NEMO.utilities import format_datetime

        start = datetime.datetime(2026, 9, 7, 14, 30)
        staff_charge = Obj(start=start)
        expected = "Active staff charge since " + format_datetime(staff_charge.start)
        actual = self.render("staff_charge_reminder_email", {"staff_charge": staff_charge})
        self.assertEqual(actual, expected)

    def test_task_status_notification(self):
        task = Obj(tool=Obj(_str="SEM"))
        self.assertEqual(self.render("task_status_notification", {"task": task}), f"{task.tool} task notification")

    def test_tool_qualification_expiration_email(self):
        tool = Obj(name="SEM")
        for remaining_days in (5, None):
            if remaining_days:
                subject_expiration = f" expires in {remaining_days} days!"
            else:
                subject_expiration = " has expired"
            expected = f"Your {tool.name} qualification {subject_expiration}"
            actual = self.render(
                "tool_qualification_expiration_email", {"tool": tool, "remaining_days": remaining_days}
            )
            self.assertEqual(actual, expected)

    def test_tool_required_unanswered_questions_email(self):
        tool = Obj(name="SEM")
        expected = f"Unanswered post‑usage questions after logoff from the {tool.name}"
        self.assertEqual(self.render("tool_required_unanswered_questions_email", {"tool": tool}), expected)

    def test_usage_reminder_email(self):
        facility_name = "NanoFab"
        self.assertEqual(self.render("usage_reminder_email", {"facility_name": facility_name}), f"{facility_name} usage")

    def test_user_access_expiration_reminder_email(self):
        import datetime

        from NEMO.utilities import format_datetime

        facility_name = "NanoFab"
        remaining_days = 14
        access_expiration = datetime.date(2026, 10, 1)
        user = Obj(access_expiration=access_expiration)
        expected = (
            f"Your {facility_name} access expires in {remaining_days} days "
            f"({format_datetime(user.access_expiration)})"
        )
        actual = self.render(
            "user_access_expiration_reminder_email",
            {"facility_name": facility_name, "remaining_days": remaining_days, "user": user},
        )
        self.assertEqual(actual, expected)

    def test_reservation_created_and_cancelled_user_email(self):
        reservation = Obj(reservation_item=Obj(_str="Laser Cutter"))
        self.assertEqual(
            self.render("reservation_created_user_email", {"reservation": reservation}),
            "Reservation for the " + str(reservation.reservation_item),
        )
        self.assertEqual(
            self.render("reservation_cancelled_user_email", {"reservation": reservation}),
            "Cancelled Reservation for the " + str(reservation.reservation_item),
        )

    def test_weekend_access_email(self):
        facility_name = "NanoFab"
        sat, sun = "09/12/2026", "09/13/2026"
        for access in (True, False):
            expected = f"{'NO w' if not access else 'W'}eekend access for the {facility_name} {sat} - {sun}"
            actual = self.render(
                "weekend_access_email",
                {"weekend_access": access, "facility_name": facility_name, "sat": sat, "sun": sun},
            )
            self.assertEqual(actual, expected)

    def test_wait_list_notification_email(self):
        tool = Obj(_str="Laser Cutter")
        self.assertEqual(
            self.render("wait_list_notification_email", {"tool": tool}), "Your turn for the " + str(tool)
        )

    def test_generic_email_intentionally_excluded(self):
        self.assertNotIn("generic_email", SUBJECT_TEMPLATES)

    def test_every_email_template_except_generic_has_a_subject_template(self):
        from NEMO.views.customization import EMAIL_TEMPLATE_NAMES

        expected_names = set(EMAIL_TEMPLATE_NAMES) - {"generic_email"}
        self.assertEqual(set(SUBJECT_TEMPLATES.keys()), expected_names)


class SubjectMigrationSafetyTestCase(NEMOTestCaseMixin, TestCase):
    """The migration's forward/reverse functions must never touch a value an admin actually set."""

    def test_forward_does_not_clobber_an_existing_customization(self):
        from NEMO.models import Customization

        # The real migration already ran while building the test database, so simulate "admin already
        # customized this" by overwriting whatever value it left, rather than assuming no row exists yet.
        Customization.objects.update_or_create(
            name="feedback_email_subject", defaults={"value": "Admin's custom subject"}
        )
        migration_module.backfill_email_subjects(apps=_RealAppsShim(), schema_editor=None)
        self.assertEqual(
            Customization.objects.get(name="feedback_email_subject").value, "Admin's custom subject"
        )

    def test_forward_overwrites_a_row_still_holding_the_inert_placeholder(self):
        # A row containing exactly "{{ default_subject }}" isn't a real customization  it's indistinguishable
        # from "never customized" (it can end up saved this way if the shared form is ever submitted without
        # editing that field), so the migration must still fill in the real subject for it.
        from NEMO.models import Customization

        Customization.objects.update_or_create(
            name="feedback_email_subject", defaults={"value": "{{ default_subject }}"}
        )
        migration_module.backfill_email_subjects(apps=_RealAppsShim(), schema_editor=None)
        self.assertEqual(
            Customization.objects.get(name="feedback_email_subject").value,
            SUBJECT_TEMPLATES["feedback_email"],
        )

    def test_reverse_does_not_delete_a_value_the_admin_changed_after_forward_ran(self):
        from NEMO.models import Customization

        migration_module.backfill_email_subjects(apps=_RealAppsShim(), schema_editor=None)
        Customization.objects.filter(name="feedback_email_subject").update(value="Admin changed this afterward")
        migration_module.remove_backfilled_email_subjects(apps=_RealAppsShim(), schema_editor=None)
        self.assertEqual(
            Customization.objects.get(name="feedback_email_subject").value, "Admin changed this afterward"
        )

    def test_reverse_removes_untouched_backfilled_rows(self):
        from NEMO.models import Customization

        migration_module.backfill_email_subjects(apps=_RealAppsShim(), schema_editor=None)
        migration_module.remove_backfilled_email_subjects(apps=_RealAppsShim(), schema_editor=None)
        self.assertFalse(Customization.objects.filter(name="feedback_email_subject").exists())


class _RealAppsShim:
    """Stands in for Django's historical `apps` registry, returning the real current model.

    Safe here because the migration's forward/reverse functions only touch the Customization table's
    unchanged (name, value) shape - there's no schema drift between the historical and current model to
    worry about for this simple data migration.
    """

    @staticmethod
    def get_model(app_label, model_name):
        from django.apps import apps as real_apps

        return real_apps.get_model(app_label, model_name)
