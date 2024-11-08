from django.conf import settings
from django.core.cache import cache
from django.utils.log import AdminEmailHandler


# Admin email override to limit the number of emails being sent when errors occur
# The default cache implementation is not shared across processes (but is thread-safe)
# If you are using gunicorn with multiple workers, each of the worker will work with its own cache
class ThrottledAdminEmailHandler(AdminEmailHandler):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.period_in_seconds = getattr(settings, "LOGGING_ERROR_EMAIL_PERIOD_SECONDS", 60)
        self.max_emails = getattr(settings, "LOGGING_ERROR_EMAIL_MAX_EMAILS", 1)
        self.cache_key = getattr(settings, "LOGGING_ERROR_EMAIL_CACHE_KEY", "error_email_admins_counter")

    def increment_counter(self):
        try:
            cache.incr(self.cache_key)
        except ValueError:
            cache.set(self.cache_key, 1, self.period_in_seconds)
        return cache.get(self.cache_key)

    def emit(self, record):
        try:
            counter = self.increment_counter()
        except Exception:
            pass
        else:
            if counter > self.max_emails:
                return
        super().emit(record)
