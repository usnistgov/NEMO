import re

from django.conf import global_settings
from rest_framework.settings import DEFAULTS

BASE_DIR = "/nemo"

# ------------------------------------------------------------------
# -------------------- Django settings for NEMO --------------------
# ------------------------------------------------------------------
# Customize these to suit your needs. Documentation can be found at:
# https://docs.djangoproject.com/en/3.2/ref/settings/

# Core settings
# DANGER: SETTING "DEBUG = True" ON A PRODUCTION SYSTEM IS EXTREMELY DANGEROUS.
# ONLY SET "DEBUG = True" FOR DEVELOPMENT AND TESTING!!!
DEBUG = False
AUTH_USER_MODEL = "NEMO.User"
DEFAULT_AUTO_FIELD = "django.db.models.AutoField"
WSGI_APPLICATION = "NEMO.wsgi.application"
ROOT_URLCONF = "NEMO.urls"

# -------------------- Session --------------------
SESSION_COOKIE_AGE = 2419200  # 2419200 seconds == 4 weeks
# Whether to expire the session when the user closes their browser
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
# Whether to use a secure cookie for the session cookie. If this is set to True, the cookie will be marked as “secure”,
# which means browsers may ensure that the cookie is only sent under an HTTPS connection.
SESSION_COOKIE_SECURE = False  # Set to True if you have an HTTPS Certificate installed

# -------------------- CSRF --------------------
# Whether to use a secure cookie for the CSRF cookie. If this is set to True, the cookie will be marked as “secure”,
# which means browsers may ensure that the cookie is only sent with an HTTPS connection.
CSRF_COOKIE_SECURE = False  # Set to True if you have an HTTPS Certificate installed
# Set to None to use session-based CSRF cookies, which keep the cookies in-memory instead of persistent storage
CSRF_COOKIE_AGE = None  # Keeps the cookies in-memory
# Whether to store the CSRF token in the user's session vs in a cookie
CSRF_USE_SESSIONS = False  # Using cookie

# -------------------- Security --------------------
# If True, the SecurityMiddleware sets the "X-XSS-Protection: 1; mode=block" header
# on all responses that do not already have it.
SECURE_BROWSER_XSS_FILTER = True
# If True, the SecurityMiddleware sets the "X-Content-Type-Options: nosniff" header
# on all responses that do not already have it.
SECURE_CONTENT_TYPE_NOSNIFF = True
# If set to a non-zero integer value, the SecurityMiddleware sets the HTTP Strict Transport Security header
# on all responses that do not already have it.
SECURE_HSTS_SECONDS = 15768000
# If True, the SecurityMiddleware adds the includeSubDomains directive to the HTTP Strict Transport Security header.
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
# If True, the SecurityMiddleware redirects all non-HTTPS requests to HTTPS
# (except for those URLs matching a regular expression listed in SECURE_REDIRECT_EXEMPT).
SECURE_SSL_REDIRECT = False  # Set to True if you have an HTTPS Certificate installed
# Set to "DENY" to prevent frames even from the same server
X_FRAME_OPTIONS = "SAMEORIGIN"

# -------------------- Authentication URLs --------------------
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "login"

# -------------------- Date and time formats --------------------
# See allowed formats at https://docs.djangoproject.com/en/3.2/ref/templates/builtins/#std:templatefilter-date
# Those formats are used ONLY IF USE_L10N = False (see below)
DATETIME_FORMAT = "l, F jS, Y @ g:i A"
SHORT_DATETIME_FORMAT = "m/d/Y @ g:i A"
DATE_FORMAT = "l, F jS, Y"
SHORT_DATE_FORMAT = "m/d/Y"
TIME_FORMAT = "g:i A"
# This format is used on the status dashboard and jumbotron when displaying since when the user has been logged in.
MONTH_DAY_FORMAT = "l m/d"

# Date and time formats, used in file names when exporting data
EXPORT_DATE_FORMAT = "m_d_Y"
EXPORT_TIME_FORMAT = "h_i_s"

# -------------------- Input date and time formats --------------------
# See allowed formats at https://docs.python.org/3/library/datetime.html#strftime-strptime-behavior
DATETIME_INPUT_FORMATS = ["%m/%d/%Y %I:%M:%S %p", *global_settings.DATE_INPUT_FORMATS]
DATE_INPUT_FORMATS = ["%m/%d/%Y", *global_settings.DATE_INPUT_FORMATS]
TIME_INPUT_FORMATS = ["%I:%M:%S %p", *global_settings.TIME_INPUT_FORMATS]

# -------------------- Pick date and time formats --------------------
# Those formats are optional in most cases and only used on kiosk or mobile views, when picking up date/time separately.
# If not defined, a conversion from DATE_INPUT_FORMATS and TIME_INPUT_FORMATS will be attempted.
# See allowed date formats at https://amsul.ca/pickadate.js/date/#formatting-rules
# See allowed time formats at https://amsul.ca/pickadate.js/time/#formatting-rules
# PICKADATE_DATE_FORMAT = "mm/dd/yyyy"
# PICKADATE_TIME_FORMAT = "HH:i A"


# -------------------- Internationalization and localization --------------------
# A boolean that specifies whether Django’s translation system should be enabled.
# This provides an easy way to turn it off, for performance.
# If this is set to False, Django will make some optimizations so as not to load the translation machinery.
USE_I18N = False
# A boolean that specifies if localized formatting of data will be enabled by default or not.
# If this is set to True, e.g. Django will display numbers and dates using the format of the current locale
USE_L10N = False
# A boolean that specifies if datetimes will be timezone-aware by default or not. If this is set to True,
# Django will use timezone-aware datetimes internally. Otherwise, Django will use naive datetimes in local time.
USE_TZ = True

# -------------------- Installed Apps --------------------
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.admin",
    "django.contrib.humanize",
    "NEMO.apps.kiosk",  # Comment out if you are not planning on using the Kiosk tablet pages
    "NEMO.apps.area_access",  # Comment out if you are not planning on using the Area Access tablets screen
    "NEMO",
    "rest_framework",
    "rest_framework.authtoken",
    "django_filters",
    "mptt",
    "auditlog",
]

# -------------------- Middleware Settings --------------------
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django.middleware.common.BrokenLinkEmailsMiddleware",
    "NEMO.middleware.DeviceDetectionMiddleware",
    # Needed for LDAP and non-SSO authentication. Adds a middleware to identify when the user's session has expired.
    "NEMO.middleware.SessionTimeout",
    # Needed for Nginx and remote user Authentication. Adds a middleware to look for remote user in http header.
    # "NEMO.middleware.HTTPHeaderAuthenticationMiddleware",
    # Needed for development setup with REMOTE_USER environment variable
    # "NEMO.middleware.RemoteUserAuthenticationMiddleware",
    # This needs to be added AFTER any kind of authentication middleware
    "NEMO.middleware.ImpersonateMiddleware",
    # This needs to be set AFTER ImpersonateMiddleware to correctly set the user in the audit log. If set before
    # the ImpersonateMiddleware, the admin user will be the one recorded as making changes, not the impersonated user.
    "NEMO.middleware.NEMOAuditlogMiddleware",
]

# By default, HTTPHeaderAuthenticationMiddleware will look in the `AUTHORIZATION` HTTP header.
AUTHENTICATION_HEADER = "AUTHORIZATION"

# -------------------- Template Settings --------------------
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "NEMO.context_processors.show_logout_button",  # Needed for LDAP and other non-SSO authentication
                # "NEMO.context_processors.hide_logout_button",  # Needed for SSO authentication
                "NEMO.context_processors.base_context",
                "django.contrib.auth.context_processors.auth",
                "django.template.context_processors.debug",
                "django.template.context_processors.media",
                "django.template.context_processors.static",
                "django.template.context_processors.tz",
                "django.template.context_processors.request",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]

# -------------------- Third party Django addons for NEMO --------------------
# These are third party capabilities that NEMO employs. They are documented on
# the respective project sites. Only customize these if you know what you're doing.

# Django REST framework:
# http://www.django-rest-framework.org/
REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": ("NEMO.permissions.DjangoModelPermissions",),
    "DEFAULT_FILTER_BACKENDS": ("NEMO.rest_filter_backend.NEMOFilterBackend",),
    # Uncomment to add token authentication option.
    # "DEFAULT_AUTHENTICATION_CLASSES": ("rest_framework.authentication.TokenAuthentication", "rest_framework.authentication.SessionAuthentication"),
    "DEFAULT_RENDERER_CLASSES": DEFAULTS["DEFAULT_RENDERER_CLASSES"] + ["drf_excel.renderers.XLSXRenderer"],
    "DEFAULT_PARSER_CLASSES": DEFAULTS["DEFAULT_PARSER_CLASSES"] + ["NEMO.parsers.CSVParser"],
    "DEFAULT_PAGINATION_CLASS": "NEMO.rest_pagination.NEMOPageNumberPagination",
    "PAGE_SIZE": 1000,
    # Formats used when exporting data in REST API (for export in json, excel, html etc.)
    # "DATETIME_FORMAT": "%m-%d-%Y %H:%M:%S",
    # "DATE_FORMAT": "%m-%d-%Y",
    # "TIME_FORMAT": "%H:%M:%S",
}


# -------------------- Organization specific settings (officially supported by Django) --------------------

# ALLOWED_HOSTS = ["*"] # "*" allows any domain. Use at your own risk. Not recommended.
ALLOWED_HOSTS = ["nemo.mydomain.com", "localhost", "192.168.1.2"]  # Preferred way of specifying allowed hosts.
# Change this SERVER_DOMAIN setting to specify the server domain to use for building links when
# a request IS NOT available (for email reminders and other timed services).
SERVER_DOMAIN = "https://{}".format(ALLOWED_HOSTS[0])
# When a request IS available, django will use the request server name, or the HTTP_HOST header if provided,
# or the X_FORWARDED_HOST header if the following setting is uncommented.
# Uncomment the following line to use the "X_FORWARDED_HOST" header of the web server to build URLs.
# This header needs to be configured in your Nginx/Apache web server. The host also needs to be in ALLOWED_HOSTS.
# USE_X_FORWARDED_HOST = True
CSRF_TRUSTED_ORIGINS = ["https://{}".format(ALLOWED_HOSTS[0])]

# -------------------- Elevated roles --------------------
# Admins will receive error emails when email admin handler is set in the logging configuration
ADMINS = [("Captain", "captain@mydomain.com")]
MANAGERS = ADMINS

# -------------------- Emails --------------------
# The email prefix for all NEMO communication
NEMO_EMAIL_SUBJECT_PREFIX = "[NEMO] "
# The email address that error messages come from, such as those sent to ADMINS and MANAGERS.
SERVER_EMAIL = "NEMO Administrator <admin@mydomain.com>"
# Default email address to use for various automated correspondence from the site manager(s).
DEFAULT_FROM_EMAIL = "NEMO Webmaster <webmaster@mydomain.com>"
# Change this to True to ALWAYS use DEFAULT_FROM_EMAIL as sender and use REPLY_TO with the original sender
# Useful when using a single email address (gmail) that prevents "spoofing" (sending as someone else)
EMAIL_USE_DEFAULT_AND_REPLY_TO = False
# Name of the reservation calendar invite organizer.
RESERVATION_ORGANIZER = "NEMO"
# Email used as the reservation calendar invite organizer email. Defaults to "no_reply" which is an invalid email.
# Setting a real email address here will mean that email will receive all the responses from every user after they
# accept the invitation.
RESERVATION_ORGANIZER_EMAIL = "no_reply"
# Change this default value to True if you want new users to get ICS calendar invite for reservations by default.
USER_RESERVATION_PREFERENCES_DEFAULT = False
# Change the following to split bcc users into chunks when sending broadcast emails. This can be useful to avoid trigger spam/security measures.
EMAIL_BROADCAST_BCC_CHUNK_SIZE = None

# -------------------- SMTP Server config --------------------
# Uncomment the following if using an email SMTP server
# EMAIL_HOST = "mydomain.com"
# EMAIL_PORT = 25

# -------------------- Email written to files --------------------
# Uncomment the following for testing
# EMAIL_BACKEND = "django.core.mail.backends.filebased.EmailBackend"
# EMAIL_FILE_PATH = BASE_DIR + "/emails/"

# See the list of timezones https://en.wikipedia.org/wiki/List_of_tz_database_time_zones
TIME_ZONE = "America/New_York"

# -------------------- Database --------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR + "/nemo.db",
    }
}

# Comment this line out for dev. This makes sure static files have a version to avoid
# having to clear browser cache between releases.
STATICFILES_STORAGE = "django.contrib.staticfiles.storage.ManifestStaticFilesStorage"
STATIC_ROOT = BASE_DIR + "/static/"
STATIC_URL = "/static/"
MEDIA_ROOT = BASE_DIR + "/media/"
MEDIA_URL = "/media/"

# Make this unique, and do not share it with anybody.
SECRET_KEY = "secret-key"  # Generate this for yourself. You can use `nemo generate_secret_key` to help

# -------------------- Logging --------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {"format": "NEMO %(levelname)s %(message)s"},
        "verbose": {
            "format": "%(levelname)s %(asctime)s %(module)s %(process)d %(thread)d %(message)s",
            "datefmt": "%d/%b/%Y %H:%M:%S",
        },
        "simple": {
            "format": "[%(asctime)s] %(name)s %(levelname)s %(message)s",
            "datefmt": "%d/%b/%Y %H:%M:%S",
        },
    },
    "handlers": {
        "email_admins": {
            "level": "ERROR",  # Only email admins for errors
            "class": "django.utils.log.AdminEmailHandler",
        },
        "error_file": {
            "level": "WARNING",  # Log all warnings and errors to this file
            "class": "logging.FileHandler",
            "filename": BASE_DIR + "/logs/nemo_error.log",
            "formatter": "verbose",
        },
        "file": {
            "class": "logging.FileHandler",
            "filename": BASE_DIR + "/logs/nemo.log",
            "formatter": "simple",
        },
        "console": {
            "formatter": "simple",
            "class": "logging.StreamHandler",
        },
    },
    "loggers": {
        "": {
            "handlers": ["file", "console", "error_file", "email_admins"],
            "level": "WARNING",  # Change to DEBUG when debugging
            "propagate": True,
        },
        "NEMO": {
            "level": "INFO",  # Change to DEBUG when debugging
            "propagate": True,
        },
        "django": {
            "level": "WARNING",
            "propagate": True,
        },
        "django.request": {
            "level": "ERROR",
            "propagate": True,
        },
    },
}


# -------------------- Organization specific settings (NEMO specific; NOT supported by Django) --------------------
# Customize these to suit your needs

# When true, all available URLs and NEMO functionality is enabled.
# When false, conditional URLs are removed to reduce the attack surface of NEMO.
# Reduced functionality for NEMO is desirable for the public facing version
# of the site in order to mitigate security risks.
ALLOW_CONDITIONAL_URLS = True

# When true, interlock function will be enabled and request will be made to lock/unlock interlocks.
# When false, the feature will be disabled
INTERLOCKS_ENABLED = False

# There are three options out-of-the-box to authenticate users (uncomment the one you decide on):
#   1) A decoupled remote user via HTTP HEADER method (such as Kerberos authentication from a reverse proxy etc.)
# AUTHENTICATION_BACKENDS = ["NEMO.views.authentication.NginxKerberosAuthorizationHeaderAuthenticationBackend"]
#   2) LDAP authentication from NEMO itself
# AUTHENTICATION_BACKENDS = ["NEMO.views.authentication.LDAPAuthenticationBackend"]
#   3) A REMOTE USER authentication used when developing
# AUTHENTICATION_BACKENDS = ["NEMO.views.authentication.RemoteUserAuthenticationBackend"]

# Username regex validation. For example limit usernames to only alphanumerics and underscore
# USERNAME_REGEX = "^[A-Za-z0-9_]+$"

# Specify your list of LDAP authentication servers only if you choose to use LDAP authentication
# Below is an example with a free ldap testing server. Usernames and passwords available at
# https://www.forumsys.com/tutorials/integration-how-to/ldap/online-ldap-test-server/
# LDAP_SERVERS = [
#     {
#         "url": "ldap.forumsys.com",
#         "port": 389,
#         "use_ssl": False,
#         "bind_as_authentication": False,
#         "base_dn": "dc=example,dc=com",
#     }
# ]

# NEMO can integrate with a custom Identity Service to manage user accounts on
# related computer systems, which streamlines user onboarding and offboarding.
# You would need to build this service yourself.
# IDENTITY_SERVICE = {
#     "available": False,
#     "url": "myidentityservice.com",
#     "domains": [],
# }

# Audit log. Update this list based on your audit needs. See supported fields at
# https://django-auditlog.readthedocs.io/en/latest/usage.html#settings
AUDITLOG_INCLUDE_TRACKING_MODELS = (
    # Track changes to user access expiration, roles and managed projects
    {
        "model": "NEMO.User",
        "include_fields": [
            "access_expiration",
            "is_staff",
            "is_service_personnel",
            "is_technician",
            "is_facility_manager",
            "is_superuser",
        ],
        "m2m_fields": ["managed_projects"],
    },
    # Track all project, account and Customization changes
    "NEMO.Project",
    "NEMO.Account",
    "NEMO.Customization",
    # Track all changes in charges
    "NEMO.UsageEvent",
    "NEMO.AreaAccessRecord",
    "NEMO.ConsumableWithdrawal",
    "NEMO.StaffCharge",
    "NEMO.TrainingSession",
)

# List of compiled regular expression objects describing URLs that should be ignored
# when reporting HTTP 404 errors via email
IGNORABLE_404_URLS = [
    re.compile(r"\.(php|cgi)$"),
    re.compile(r"^/phpmyadmin/"),
    re.compile(r"^/robots.txt$"),
    re.compile(r"^/apple-touch-icon.*\.png$"),
    re.compile(r"^/favicon\.ico$"),
]
