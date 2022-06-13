DEBUG = True
FIXTURE_DIRS = ['/nemo/']
ALLOWED_HOSTS = ["*"]
DEFAULT_AUTO_FIELD = 'django.db.models.AutoField'
AUTH_USER_MODEL = 'NEMO.User'
WSGI_APPLICATION = 'NEMO.wsgi.application'
ROOT_URLCONF = 'NEMO.urls'

LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'login'

DATETIME_FORMAT = "l, F jS, Y @ g:i A"
SHORT_DATETIME_FORMAT = "m/d/Y @ g:i A"
DATE_FORMAT = "l, F jS, Y"
SHORT_DATE_FORMAT = "m/d/Y"
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
	'NEMO.apps.kiosk',
	'NEMO.apps.area_access',
	'NEMO.apps.sensors',
	'rest_framework',
	'django_filters',
	'mptt',
]

MIDDLEWARE = [
	'django.middleware.security.SecurityMiddleware',
	'django.middleware.common.CommonMiddleware',
	'django.contrib.sessions.middleware.SessionMiddleware',
	'django.middleware.csrf.CsrfViewMiddleware',
	'django.contrib.auth.middleware.AuthenticationMiddleware',
	'django.contrib.messages.middleware.MessageMiddleware',
	'django.middleware.clickjacking.XFrameOptionsMiddleware',
	'django.middleware.common.BrokenLinkEmailsMiddleware',
	'NEMO.middleware.DeviceDetectionMiddleware',
	'NEMO.middleware.RemoteUserAuthenticationMiddleware',
	'NEMO.middleware.ImpersonateMiddleware',
]

TEMPLATES = [
	{
		'BACKEND': 'django.template.backends.django.DjangoTemplates',
		'APP_DIRS': True,
		'OPTIONS': {
			'context_processors': [
				'NEMO.context_processors.hide_logout_button',  # Add a 'request context processor' in order to figure out whether to display the logout button. If the site is configured to use the LDAP authentication backend then we want to provide a logoff button (in the menu bar). Otherwise the Kerberos authentication backend is used and no logoff button is necessary.
				'NEMO.context_processors.base_context',  # Informs the templating engine whether the template is being rendered for a desktop or mobile device.
				'django.contrib.auth.context_processors.auth',
				'django.template.context_processors.debug',
				'django.template.context_processors.media',
				'django.template.context_processors.static',
				'django.template.context_processors.tz',
				'django.template.context_processors.request',
				'django.contrib.messages.context_processors.messages',
			],
		},
	},
]

REST_FRAMEWORK = {
	'DEFAULT_PERMISSION_CLASSES': ('NEMO.permissions.BillingAPI',),
	'DEFAULT_FILTER_BACKENDS': ('django_filters.rest_framework.DjangoFilterBackend',),
	'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
	'PAGE_SIZE': 1000,
}

SERVER_EMAIL = 'NEMO Server Administrator <nemo.admin@example.org>'

ADMINS = [
	('System administrator', 'sysadmin@example.org'),
]
MANAGERS = ADMINS

EMAIL_HOST = 'mail.example.org'
EMAIL_PORT = 25

TIME_ZONE = 'America/New_York'

DATABASES = {
	'default': {
		'ENGINE': 'django.db.backends.sqlite3',
		'NAME': '/nemo/sqlite.db',
	}
}

STATIC_URL = '/static/'
MEDIA_ROOT = '/nemo/media/'
MEDIA_URL = '/media/'

SECRET_KEY = 'abc123'

ALLOW_CONDITIONAL_URLS = True
AUTHENTICATION_BACKENDS = ['NEMO.views.authentication.RemoteUserAuthenticationBackend']

IDENTITY_SERVICE = {
	'available': False,
	'url': 'https://identity.example.org/',
	'domains': [],
}
