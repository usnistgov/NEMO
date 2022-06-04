from rest_framework import permissions

class BillingAPI(permissions.BasePermission):
	""" Checks that a user has permission to use the NEMO RESTful API for billing purposes.
		This is a global permission and will give the user access to all API objects."""

	def has_permission(self, request, view):
		if request and request.user.has_perm('NEMO.use_billing_api'):
			return True
		return False


class DjangoModelPermissions(permissions.DjangoModelPermissions):
	""" Checks that a user has the correct model permission (including view) to use the NEMO RESTful API. """
	perms_map = {
		'GET': ['%(app_label)s.view_%(model_name)s'],
		'OPTIONS': [],
		'HEAD': [],
		'POST': ['%(app_label)s.add_%(model_name)s'],
		'PUT': ['%(app_label)s.change_%(model_name)s'],
		'PATCH': ['%(app_label)s.change_%(model_name)s'],
		'DELETE': ['%(app_label)s.delete_%(model_name)s'],
	}
