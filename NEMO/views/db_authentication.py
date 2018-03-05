# /home/nemo/python/lib/python3.6/site-packages/NEMO/views/
# settings.py: AUTHENTICATION_BACKENDS = ['NEMO.views.db_authentication.DbAuthenticationBackend']

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password

from NEMO.models import UserAuth

class DbAuthenticationBackend:

    def authenticate(self, username=None, password=None):
        User = get_user_model()
        try:
            user_auth = UserAuth.objects.get(username=username)
            if user_auth.validate_password(password):
                user = User.objects.get(username=username)
                return user
        except:
            return None
        return None

    def get_user(self, user_id):
        User = get_user_model()
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None

