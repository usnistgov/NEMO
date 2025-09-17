from smtplib import SMTPConnectError, SMTPServerDisconnected
from unittest.mock import patch

from django.test import TestCase

from NEMO.tests.test_utilities import NEMOTestCaseMixin
from NEMO.utilities import send_mail


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

    @patch(
        "NEMO.utilities.EmailMessage.send",
        side_effect=[SMTPServerDisconnected(), SMTPConnectError(451, "Temporary error")],
    )
    def test_send_mail_fails_after_max_retries(self, mock_send):
        result = send_mail(self.subject, self.content, self.from_email, self.to, fail_silently=True)
        self.assertEqual(result, 0)
        self.assertEqual(mock_send.call_count, 2)
