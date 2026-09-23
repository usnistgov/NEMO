from smtplib import SMTPConnectError, SMTPDataError, SMTPException, SMTPServerDisconnected, SMTPHeloError
from unittest.mock import patch

from django.core import mail
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings

from NEMO.models import User
from NEMO.tests.test_utilities import NEMOTestCaseMixin
from NEMO.utilities import send_mail
from NEMO.views.customization import TemplatesCustomization


class TestSendMailRetries(NEMOTestCaseMixin, TestCase):
    def setUp(self):
        self.subject = "Retry Test"
        self.content = "<p>Testing retry logic</p>"
        self.from_email = "test@example.com"
        self.to = ["recipient@example.com"]
        self.fail_silently = True

    @patch("NEMO.utilities.EmailMessage.send", side_effect=[SMTPServerDisconnected(), 1])
    def test_send_mail_retries_on_disconnection(self, mock_send):
        result = send_mail(self.subject, self.content, self.from_email, self.to, fail_silently=True)
        self.assertEqual(result, 1)
        self.assertEqual(mock_send.call_count, 2)

    @patch("NEMO.utilities.EmailMessage.send", side_effect=[SMTPConnectError(451, "Temporary error"), 1])
    def test_send_mail_retries_on_connect_error(self, mock_send):
        result = send_mail(self.subject, self.content, self.from_email, self.to, fail_silently=True)
        self.assertEqual(result, 1)
        self.assertEqual(mock_send.call_count, 2)

    @patch("NEMO.utilities.EmailMessage.send", side_effect=[SMTPHeloError(451, "Helo error"), 1])
    def test_send_mail_retries_on_helo_error(self, mock_send):
        result = send_mail(self.subject, self.content, self.from_email, self.to, fail_silently=True)
        self.assertEqual(result, 1)
        self.assertEqual(mock_send.call_count, 2)

    @patch("NEMO.utilities.EmailMessage.send", side_effect=[SMTPDataError(451, "Data error"), 1])
    def test_send_mail_retries_on_data_error(self, mock_send):
        result = send_mail(self.subject, self.content, self.from_email, self.to, fail_silently=True)
        self.assertEqual(result, 1)
        self.assertEqual(mock_send.call_count, 2)

    @patch(
        "NEMO.utilities.EmailMessage.send",
        side_effect=[SMTPServerDisconnected(), SMTPConnectError(451, "Temporary error")],
    )
    def test_send_mail_fails_after_max_retries(self, mock_send):
        result = send_mail(self.subject, self.content, self.from_email, self.to, fail_silently=True)
        self.assertEqual(result, 0)
        self.assertEqual(mock_send.call_count, 2)


@patch("django.core.files.storage.FileSystemStorage.exists", return_value=True)
@patch("django.core.files.storage.FileSystemStorage._open")
class BroadcastEmailCcTestCase(NEMOTestCaseMixin, TestCase):
    """A customized generic_email cc must be sent independently of the bcc chunks: exactly once, resilient to
    a bcc chunk failure, and never duplicated for someone who's both the cc address and an audience member."""

    def setUp(self):
        self.sender = User.objects.create(
            username="sender", first_name="S", last_name="S", email="sender@example.com", is_staff=True,
            is_superuser=True,
        )
        self.login_as(self.sender)

    def configure_mock_open(self, mock_open):
        # A fresh ContentFile per test: it's a stream, and mock.return_value set once at decoration time
        # (e.g. via @patch(..., return_value=...)) would be shared and exhausted across every test in the
        # class after the first .read().
        mock_open.return_value = ContentFile(b"<p>{{ contents }}</p>", name="generic_email.html")

    def tearDown(self):
        TemplatesCustomization.set("generic_email_cc", "")
        super().tearDown()

    def post_broadcast(self, subject="Test broadcast"):
        return self.client.post(
            "/send_broadcast_email/",
            {
                "audience": "user",
                "no_type": "",
                "title": "t",
                "greeting": "g",
                "contents": "c",
                "color": "#5bc0de",
                "subject": subject,
                "send_to_inactive_users": "",
                "send_to_expired_access_users": "",
                "copy_me": "",
            },
        )

    @override_settings(EMAIL_BROADCAST_BCC_CHUNK_SIZE=2)
    def test_cc_sent_as_its_own_message_not_duplicated_per_chunk(self, mock_open, mock_exists):
        self.configure_mock_open(mock_open)
        for i in range(5):
            User.objects.create(username=f"u{i}", first_name="F", last_name="L", email=f"u{i}@example.com")
        TemplatesCustomization.set("generic_email_cc", "manager@example.com")

        response = self.post_broadcast()

        self.assertEqual(response.status_code, 302)
        cc_emails = [m for m in mail.outbox if m.to == ["manager@example.com"]]
        self.assertEqual(len(cc_emails), 1, "cc address should receive exactly one email, not one per chunk")
        self.assertGreater(len(mail.outbox), 1, "sanity check: audience should have been split into multiple chunks")

    @override_settings(EMAIL_BROADCAST_BCC_CHUNK_SIZE=2)
    def test_cc_failure_does_not_block_the_bcc_chunks(self, mock_open, mock_exists):
        self.configure_mock_open(mock_open)
        for i in range(5):
            User.objects.create(username=f"u{i}", first_name="F", last_name="L", email=f"u{i}@example.com")
        TemplatesCustomization.set("generic_email_cc", "manager@example.com")

        with patch("NEMO.views.email.send_mail") as mock_send:

            def side_effect(*args, **kwargs):
                if kwargs.get("to") == ["manager@example.com"]:
                    raise SMTPException("simulated cc failure")
                return 1

            mock_send.side_effect = side_effect
            response = self.post_broadcast()

        # The broadcast overall still succeeds (redirect, not the hard-failure path) even though the
        # independent cc send failed - only the bcc chunks' success determines the main outcome.
        self.assertEqual(response.status_code, 302)
        self.assertEqual(mock_send.call_count, 4)  # 1 attempted cc send + 3 bcc chunks

    def test_cc_address_that_is_also_in_the_audience_gets_exactly_one_email(self, mock_open, mock_exists):
        self.configure_mock_open(mock_open)
        User.objects.create(username="u0", first_name="F", last_name="L", email="u0@example.com")
        User.objects.create(username="u1", first_name="F", last_name="L", email="u1@example.com")
        TemplatesCustomization.set("generic_email_cc", "u0@example.com")

        self.post_broadcast()

        all_recipients = [addr for m in mail.outbox for addr in (m.to + m.cc + m.bcc)]
        self.assertEqual(all_recipients.count("u0@example.com"), 1)

    def test_audience_entirely_overlapping_cc_does_not_crash(self, mock_open, mock_exists):
        self.configure_mock_open(mock_open)
        User.objects.create(username="onlyuser", first_name="F", last_name="L", email="only@example.com")
        TemplatesCustomization.set("generic_email_cc", "only@example.com, sender@example.com")

        response = self.post_broadcast()

        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
