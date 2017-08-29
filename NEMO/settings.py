# -------------------- Django settings for NEMO --------------------
# Do NOT customize these settings for your organization.

# Core settings
DEBUG = False
AUTH_USER_MODEL = 'NEMO.User'
WSGI_APPLICATION = 'NEMO.wsgi.application'
ROOT_URLCONF = 'NEMO.urls'

# Information security
SESSION_COOKIE_AGE = 1800  # 1800 seconds == 30 minutes
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
#SESSION_COOKIE_SECURE = True
#CSRF_COOKIE_SECURE = True
CSRF_COOKIE_AGE = None
X_FRAME_OPTIONS = 'DENY'
#SECURE_BROWSER_XSS_FILTER = True
#SECURE_CONTENT_TYPE_NOSNIFF = True
#SECURE_HSTS_INCLUDE_SUBDOMAINS = True
#SECURE_HSTS_SECONDS = 15768000
#SECURE_SSL_REDIRECT = True

# Authentication
LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'login'

# Date and time formats
DATETIME_FORMAT = "l, F jS, Y @ g:i A"
DATE_FORMAT = "m/d/Y"
TIME_FORMAT = "g:i A"
DATETIME_INPUT_FORMATS = ['%m/%d/%Y %I:%M %p']
DATE_INPUT_FORMATS = ['%m/%d/%Y']
TIME_INPUT_FORMATS = ['%I:%M %p']

USE_I18N = False
USE_L10N = False
USE_TZ = True

INSTALLED_APPS = [
	'django.contrib.auth',
	'django.contrib.contenttypes',
	'django.contrib.sessions',
	'django.contrib.messages',
	'django.contrib.staticfiles',
	'django.contrib.admin',
	'django.contrib.humanize',
	'NEMO',
	'rest_framework',
]

MIDDLEWARE = [
	'django.middleware.security.SecurityMiddleware',
	'django.middleware.common.CommonMiddleware',
	'django.contrib.sessions.middleware.SessionMiddleware',
	'django.middleware.csrf.CsrfViewMiddleware',
	'django.contrib.auth.middleware.AuthenticationMiddleware',
	'django.contrib.auth.middleware.RemoteUserMiddleware',
	'django.contrib.messages.middleware.MessageMiddleware',
	'django.middleware.clickjacking.XFrameOptionsMiddleware',
	'django.middleware.common.BrokenLinkEmailsMiddleware',
	'NEMO.middleware.DeviceDetectionMiddleware',
]

TEMPLATES = [
	{
		'BACKEND': 'django.template.backends.django.DjangoTemplates',
		'APP_DIRS': True,
		'OPTIONS': {
			'context_processors': [
				'NEMO.context_processors.logout_allowed',  # Add a 'request context processor' in order to figure out whether to display the logout button. If the site is configured to use the LDAP authentication backend then we want to provide a logoff button (in the menu bar). Otherwise the Kerberos authentication backend is used and no logoff button is necessary.
				'NEMO.context_processors.device',  # Informs the templating engine whether the template is being rendered for a desktop or mobile device.
				'django.contrib.auth.context_processors.auth',
				'django.template.context_processors.debug',
				'django.template.context_processors.media',
				'django.template.context_processors.static',
				'django.template.context_processors.tz',
				'django.contrib.messages.context_processors.messages',
			],
		},
	},
]


def get_file_contents(path):
	with open(path) as f:
		return f.read().strip()


# -------------------- Third party Django addons for NEMO --------------------
# These are third party capabilities that NEMO employs. They are documented on
# the respective project sites. Only customize these if you know what you're doing.

# Django REST framework:
# http://www.django-rest-framework.org/
REST_FRAMEWORK = {
	'DEFAULT_PERMISSION_CLASSES': ('NEMO.permissions.BillingAPI',),
	'DEFAULT_FILTER_BACKENDS': ('rest_framework.filters.DjangoFilterBackend',),
	'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
	'PAGE_SIZE': 1000,
}


# ------------ Organization specific settings (officially supported by Django) ------------
# Customize these to suit your needs. Documentation can be found at:
# https://docs.djangoproject.com/en/1.11/ref/settings/

ALLOWED_HOSTS = [
	'localhost',
]

SERVER_EMAIL = 'NEMO Server Administrator <webmaster@example.org>'

ADMINS = [
	('Tony Stark', 'ironman@example.org'),
	('Steve Rogers', 'cap@example.org'),
	('Bruce Banner', 'hulk@example.org'),
]
MANAGERS = ADMINS

EMAIL_HOST = 'mail.example.org'
EMAIL_PORT = 25
#EMAIL_BACKEND = 'django.core.mail.backends.filebased.EmailBackend'
#EMAIL_FILE_PATH = '/path/to/email_sink'

TIME_ZONE = 'America/New_York'

DATABASES = {
	'default': {
		'ENGINE': 'django.db.backends.sqlite3',
		'NAME': '/path/to/sqlite.db',
	}
}

STATIC_ROOT = '/path/to/static'
STATIC_URL = '/static/'
MEDIA_ROOT = '/path/to/media'
MEDIA_URL = '/media/'

# Make this unique, and don't share it with anybody.
SECRET_KEY = get_file_contents('/path/to/django_secret_key.txt')


# ------------ Organization specific settings (NEMO specific; NOT supported by Django) ------------
# Customize these to suit your needs

# When true, all available URLs and NEMO functionality is enabled.
# When false, conditional URLs are removed to reduce the attack surface of NEMO.
# Reduced functionality for NEMO is desirable for the public facing version
# of the site in order to mitigate security risks.
ALLOW_CONDITIONAL_URLS = True

# There are two options to authenticate users:
#   1) A decoupled "REMOTE_USER" method (such as Kerberos authentication from a reverse proxy)
#   2) LDAP authentication from NEMO itself
AUTHENTICATION_BACKENDS = ['NEMO.views.authentication.RemoteUserAuthenticationBackend']

# Specify your list of LDAP authentication servers only if you choose to use LDAP authentication.
# If you are not using LDAP then set this to be an empty list [].
LDAP_SERVERS = [
	{
		'url': 'ldap.example.org',
		'domain': 'EXAMPLE.ORG',
		'certificate': '/path/to/example.org.public.cert',
	},
	{
		'url': 'ldap.another.org',
		'domain': 'ANOTHER.ORG',
		'certificate': '/path/to/another.org.public.cert',
	},
]

# NEMO can integrate with a custom Identity Service to manage user accounts on
# related computer systems, which streamlines user onboarding and offboarding.
IDENTITY_SERVICE = {
	'available': False,
	'url': 'https://identity.example.org/',
	'domains': ['EXAMPLE.ORG', 'ANOTHER.ORG'],
}
