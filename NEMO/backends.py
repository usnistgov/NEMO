from django.conf import settings
from django.core.mail.backends.smtp import EmailBackend


class OverrideSmtpEmailBackend(EmailBackend):
    def send_messages(self, email_messages):
        email_override = getattr(settings, "EMAIL_OVERRIDE", [])
        # Throw an error if EMAIL_OVERRIDE was not defined or set to an empty list
        if not email_override:
            raise NameError("Email override failed: No recipients in EMAIL_OVERRIDE in setting.")
        for message in email_messages:
            # Add original recipients to email, processing backwards so order is to, cc, bcc in the final string.
            for bccAddress in message.bcc:
                message.body = message.body.replace("<body>", f"<body>Original Bcc: {bccAddress}<br />")
            for ccAddress in message.cc:
                message.body = message.body.replace("<body>", f"<body>Original Cc: {ccAddress}<br />")
            for toAddress in message.to:
                message.body = message.body.replace("<body>", f"<body>Original To: {toAddress}<br />")
            # Override recipients list for all outgoing emails
            message.to = [email_override]
            message.cc = []
            message.bcc = []
        return super().send_messages(email_messages)
