from rest_framework import permissions


class BillingAPI(permissions.BasePermission):
	""" Checks that a user has permission to use the NEMO RESTful API for billing purposes. """
	def has_permission(self, request, view):
		if request and request.user.has_perm('NEMO.use_billing_api'):
				return True
		return False
