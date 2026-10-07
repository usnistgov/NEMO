from unittest.mock import patch

from django.core import mail
from django.core.files.base import ContentFile
from django.test import TestCase
from django.urls import reverse

from NEMO.models import User
from NEMO.tests.test_utilities import NEMOTestCaseMixin
from NEMO.views.customization import (
    EMAIL_TEMPLATE_NAMES,
    EmailsCustomization,
    TemplatesCustomization,
    resolve_email_customization,
)


class ResolveEmailCustomizationTestCase(NEMOTestCaseMixin, TestCase):
    def setUp(self):
        self.dictionary = {
            "default_subject": "Original subject",
            "default_from_email": "orig@example.com",
            "default_cc_emails": "a@example.com, b@example.com",
        }
        # The backfill migration backfills real subject templates for these two, which would otherwise make the
        # "not customized" tests below fail. These tests are about resolve_email_customization()'s generic
        # override/passthrough/independence mechanics, not migration content, so we start from a clean slate.
        from NEMO.models import Customization

        Customization.objects.filter(
            name__in=[
                "new_task_email_subject",
                "new_task_email_from",
                "new_task_email_cc",
                "task_status_notification_subject",
                "task_status_notification_from",
                "task_status_notification_cc",
            ]
        ).delete()

    def test_defaults_pass_through_when_not_customized(self):
        subject, from_email, cc = resolve_email_customization("new_task_email", self.dictionary)
        self.assertEqual(subject, "Original subject")
        self.assertEqual(from_email, "orig@example.com")
        self.assertEqual(cc, ["a@example.com", "b@example.com"])

    def test_customized_subject_can_reference_default_subject(self):
        TemplatesCustomization.set("new_task_email_subject", "Custom: {{ default_subject }}")
        subject, from_email, cc = resolve_email_customization("new_task_email", self.dictionary)
        self.assertEqual(subject, "Custom: Original subject")
        # from/cc remain at their (unset) defaults
        self.assertEqual(from_email, "orig@example.com")
        self.assertEqual(cc, ["a@example.com", "b@example.com"])

    def test_customized_from_overrides_default(self):
        TemplatesCustomization.set("new_task_email_from", "override@example.com")
        _, from_email, _ = resolve_email_customization("new_task_email", self.dictionary)
        self.assertEqual(from_email, "override@example.com")

    def test_cc_is_split_stripped_and_empty_entries_dropped(self):
        TemplatesCustomization.set("new_task_email_cc", "c@example.com,  d@example.com , , ")
        _, _, cc = resolve_email_customization("new_task_email", self.dictionary)
        self.assertEqual(cc, ["c@example.com", "d@example.com"])

    def test_cc_can_reference_arbitrary_context_variables(self):
        dictionary = dict(self.dictionary, extra_cc="extra@example.com")
        TemplatesCustomization.set("new_task_email_cc", "{{ default_cc_emails }}, {{ extra_cc }}")
        _, _, cc = resolve_email_customization("new_task_email", dictionary)
        self.assertEqual(cc, ["a@example.com", "b@example.com", "extra@example.com"])

    def test_resetting_to_empty_falls_back_to_default(self):
        TemplatesCustomization.set("new_task_email_subject", "Custom")
        TemplatesCustomization.set("new_task_email_subject", "")
        subject, _, _ = resolve_email_customization("new_task_email", self.dictionary)
        self.assertEqual(subject, "Original subject")

    def test_different_templates_are_independent(self):
        TemplatesCustomization.set("new_task_email_subject", "New task custom subject")
        subject, _, _ = resolve_email_customization("task_status_notification", self.dictionary)
        self.assertEqual(subject, "Original subject")


class TemplatesCustomizationEmailVariablesTestCase(NEMOTestCaseMixin, TestCase):
    def test_every_email_template_has_subject_from_cc_variables(self):
        for name in EMAIL_TEMPLATE_NAMES:
            self.assertIn(f"{name}_subject", TemplatesCustomization.variables)
            self.assertIn(f"{name}_from", TemplatesCustomization.variables)
            self.assertIn(f"{name}_cc", TemplatesCustomization.variables)

    def test_variable_count_matches_three_per_email_template(self):
        email_variable_names = [
            key
            for key in TemplatesCustomization.variables
            if key.endswith(("_subject", "_from", "_cc")) and key.rsplit("_", 1)[0] in EMAIL_TEMPLATE_NAMES
        ]
        self.assertEqual(len(email_variable_names), len(EMAIL_TEMPLATE_NAMES) * 3)

    def test_non_email_files_do_not_get_subject_variables(self):
        # login_banner is a files entry but not an actual email - it must not get subject/from/cc variables
        self.assertNotIn("login_banner_subject", TemplatesCustomization.variables)
        self.assertNotIn("jumbotron_watermark_subject", TemplatesCustomization.variables)

    def test_defaults_are_passthrough_templates(self):
        # The class-level Python default (used whenever a template has no DB row at all - e.g. a template the
        # backfill migration doesn't touch, or one an admin has reset to blank) must still be the plain passthrough.
        self.assertEqual(TemplatesCustomization.variables["feedback_email_subject"], "{{ default_subject }}")
        self.assertEqual(TemplatesCustomization.variables["feedback_email_from"], "{{ default_from_email }}")
        self.assertEqual(TemplatesCustomization.variables["feedback_email_cc"], "{{ default_cc_emails }}")


@patch("django.core.files.storage.FileSystemStorage.exists")
@patch("django.core.files.storage.FileSystemStorage._open")
class FeedbackEmailCustomizationEndToEndTestCase(NEMOTestCaseMixin, TestCase):
    """Verifies a customized subject/from/cc is actually used when an email is sent, via the feedback view."""

    def setUp(self):
        self.user = User.objects.create(
            username="feedback_user", first_name="Feed", last_name="Back", email="feedback_user@example.com"
        )
        EmailsCustomization.set("feedback_email_address", "recipient@example.com")

    def tearDown(self):
        TemplatesCustomization.set("feedback_email_subject", "")
        TemplatesCustomization.set("feedback_email_from", "")
        TemplatesCustomization.set("feedback_email_cc", "")
        super().tearDown()

    def test_default_subject_and_from_are_used_when_not_customized(self, mock_open, mock_exists):
        mock_exists.return_value = True
        mock_open.return_value = ContentFile(b"<p>{{ contents }}</p>", name="feedback_email.html")
        self.login_as(self.user)
        self.client.post("/feedback/", {"feedback": "Hello there"})
        self.assertEqual(len(mail.outbox), 1)
        sent = mail.outbox[0]
        self.assertEqual(sent.subject, "Feedback from " + str(self.user))
        self.assertEqual(sent.from_email, self.user.email)
        self.assertEqual(sent.cc, [])

    def test_customized_subject_from_and_cc_are_used_when_sending(self, mock_open, mock_exists):
        mock_exists.return_value = True
        mock_open.return_value = ContentFile(b"<p>{{ contents }}</p>", name="feedback_email.html")
        TemplatesCustomization.set("feedback_email_subject", "Custom: {{ default_subject }}")
        TemplatesCustomization.set("feedback_email_from", "override@example.com")
        TemplatesCustomization.set("feedback_email_cc", "cc1@example.com, cc2@example.com")
        self.login_as(self.user)
        self.client.post("/feedback/", {"feedback": "Hello there"})
        self.assertEqual(len(mail.outbox), 1)
        sent = mail.outbox[0]
        self.assertEqual(sent.subject, "Custom: Feedback from " + str(self.user))
        self.assertEqual(sent.from_email, "override@example.com")
        # send_mail() de-duplicates recipients via a set, so cc order isn't guaranteed
        self.assertEqual(sorted(sent.cc), ["cc1@example.com", "cc2@example.com"])


class CustomizeTemplatesViewTestCase(NEMOTestCaseMixin, TestCase):
    """Verifies the shared 'email settings' form saves every template's fields together without wiping others."""

    def test_saving_one_template_does_not_wipe_others(self):
        staff = self.login_as_staff()
        staff.is_superuser = True
        staff.save()

        # Give a couple of templates a pre-existing customization
        TemplatesCustomization.set("task_status_notification_subject", "Pre-existing subject")
        TemplatesCustomization.set("safety_issue_email_from", "safety-override@example.com")

        post_data = {}
        for name in EMAIL_TEMPLATE_NAMES:
            post_data[f"{name}_subject"] = TemplatesCustomization.get(f"{name}_subject")
            post_data[f"{name}_from"] = TemplatesCustomization.get(f"{name}_from")
            post_data[f"{name}_cc"] = TemplatesCustomization.get(f"{name}_cc")

        # Only change feedback_email's fields in this submission
        post_data["feedback_email_subject"] = "Newly customized subject"
        post_data["feedback_email_from"] = "new-from@example.com"
        post_data["feedback_email_cc"] = "someone@example.com"

        response = self.client.post(reverse("customize", args=["templates"]), post_data)
        self.assertEqual(response.status_code, 302)

        self.assertEqual(TemplatesCustomization.get("feedback_email_subject"), "Newly customized subject")
        self.assertEqual(TemplatesCustomization.get("feedback_email_from"), "new-from@example.com")
        self.assertEqual(TemplatesCustomization.get("feedback_email_cc"), "someone@example.com")
        # The pre-existing customizations on other templates must survive this save untouched
        self.assertEqual(TemplatesCustomization.get("task_status_notification_subject"), "Pre-existing subject")
        self.assertEqual(TemplatesCustomization.get("safety_issue_email_from"), "safety-override@example.com")

    def test_customization_page_renders_all_email_fields(self):
        staff = self.login_as_staff()
        staff.is_superuser = True
        staff.save()
        response = self.client.get(reverse("customization", args=["templates"]))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('id="email_settings_form"', content)
        for name in EMAIL_TEMPLATE_NAMES:
            self.assertIn(f'name="{name}_subject"', content)
            self.assertIn(f'name="{name}_from"', content)
            self.assertIn(f'name="{name}_cc"', content)


class PerTemplateSaveTestCase(NEMOTestCaseMixin, TestCase):
    """The per-template 'Save this email's settings' button must save only that one template's fields."""

    def setUp(self):
        staff = self.login_as_staff()
        staff.is_superuser = True
        staff.save()

    def test_saving_one_template_via_the_fields_element_does_not_touch_others(self):
        TemplatesCustomization.set("task_status_notification_subject", "Pre-existing subject")
        TemplatesCustomization.set("safety_issue_email_from", "safety-override@example.com")

        response = self.client.post(
            reverse("customize", args=["templates", "feedback_email_fields"]),
            {
                "feedback_email_subject": "Newly customized subject",
                "feedback_email_from": "new-from@example.com",
                "feedback_email_cc": "someone@example.com",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("saved=feedback_email", response.url)
        self.assertIn("#feedback_email_id", response.url)
        self.assertEqual(TemplatesCustomization.get("feedback_email_subject"), "Newly customized subject")
        self.assertEqual(TemplatesCustomization.get("feedback_email_from"), "new-from@example.com")
        self.assertEqual(TemplatesCustomization.get("feedback_email_cc"), "someone@example.com")
        # Untouched by this scoped save
        self.assertEqual(TemplatesCustomization.get("task_status_notification_subject"), "Pre-existing subject")
        self.assertEqual(TemplatesCustomization.get("safety_issue_email_from"), "safety-override@example.com")

    def test_fields_element_that_is_not_a_real_email_template_falls_back_to_the_generic_save(self):
        # "login_banner_fields" doesn't correspond to any email template, so this must behave like a normal
        # (non-scoped) save rather than silently doing nothing or raising.
        response = self.client.post(reverse("customize", args=["templates", "login_banner_fields"]), {})
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("saved=", response.url)

    def test_inline_success_banner_shown_only_for_the_saved_template(self):
        response = self.client.get(reverse("customization", args=["templates"]) + "?saved=feedback_email")
        content = response.content.decode()
        self.assertIn("This email's subject, from, and cc settings were saved successfully.", content)
        # Only one banner should appear, not one per template
        self.assertEqual(
            content.count("This email's subject, from, and cc settings were saved successfully."), 1
        )


class FileUploadSaveMessageTestCase(NEMOTestCaseMixin, TestCase):
    """Uploading a file (or saving the textarea) shows an inline confirmation under that element's own upload
    button, distinct from and never confused with the subject/from/cc banner for the same element name."""

    def setUp(self):
        staff = self.login_as_staff()
        staff.is_superuser = True
        staff.save()

    def test_uploading_a_file_redirects_with_file_saved_not_saved(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        response = self.client.post(
            reverse("customize", args=["templates", "login_banner"]),
            {"login_banner": SimpleUploadedFile("login_banner.html", b"<p>New banner</p>")},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("file_saved=login_banner", response.url)
        self.assertIn("#login_banner_id", response.url)
        self.assertNotIn("?saved=", response.url)

    def test_file_saved_banner_shown_only_under_that_uploads_button(self):
        response = self.client.get(reverse("customization", args=["templates"]) + "?file_saved=login_banner")
        content = response.content.decode()
        self.assertIn("Login banner was saved successfully.", content)
        self.assertEqual(content.count("Login banner was saved successfully."), 1)

    def test_file_saved_param_does_not_trigger_the_fields_banner_for_the_same_name(self):
        # feedback_email is both a file-upload element and a subject/from/cc element; saving one must not
        # make the other's banner appear.
        response = self.client.get(reverse("customization", args=["templates"]) + "?file_saved=feedback_email")
        content = response.content.decode()
        self.assertIn("Feedback email was saved successfully.", content)
        self.assertNotIn("This email's subject, from, and cc settings were saved successfully.", content)

    def test_saved_param_does_not_trigger_the_file_banner_for_the_same_name(self):
        response = self.client.get(reverse("customization", args=["templates"]) + "?saved=feedback_email")
        content = response.content.decode()
        self.assertIn("This email's subject, from, and cc settings were saved successfully.", content)
        self.assertNotIn("Feedback email was saved successfully.", content)

    def test_rates_customization_file_upload_also_gets_the_scoped_redirect(self):
        # The mechanism is generic (any CustomizationBase subclass with a files list), not email-specific.
        from django.core.files.uploadedfile import SimpleUploadedFile

        response = self.client.post(
            reverse("customize", args=["rates", "rates"]),
            {"rates": SimpleUploadedFile("rates.json", b"[]")},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("file_saved=rates", response.url)
