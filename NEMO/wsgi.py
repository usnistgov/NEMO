from os import environ

from django.core.wsgi import get_wsgi_application

environ['DJANGO_SETTINGS_MODULE'] = 'NEMO.settings'
application = get_wsgi_application()
