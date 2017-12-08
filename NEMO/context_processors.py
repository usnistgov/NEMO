from django.conf import settings


def logout_allowed(request):
	# Set 'logout_allowed' to True for any authentication backends that are capable of logging out.
	# LDAP is capable of logging out. Kerberos is not.
	if 'NEMO.views.authentication.LDAPAuthenticationBackend' in settings.AUTHENTICATION_BACKENDS:
		return {'logout_allowed': True}
	return {'logout_allowed': False}


def device(request):
	return {'device': request.device}
