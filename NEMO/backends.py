from django.conf import settings
from django.core.mail.backends.smtp import EmailBackend

class OverrideSmtpEmailBackend(EmailBackend):
    def send_messages(self, email_messages):
        for message in email_messages:
            # todo: Add the original to/cc/bcc fields were at top of message for easier debugging
            # Override recipients list globally
            message.to = [getattr(settings, "EMAIL_OVERRIDE", [])]
            message.cc = []
            message.bcc = []
        return super().send_messages(email_messages)