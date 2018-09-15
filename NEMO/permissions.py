import logging
from rest_framework import permissions


logger = logging.getLogger(__name__)


class BillingAPI(permissions.BasePermission):
	""" Checks that a user has permission to use the NEMO RESTful API for billing purposes. """
	def has_permission(self, request, view):
		if request and request.user.has_perm('NEMO.use_billing_api'):
			logger.debug(f"user [{request.user}] was granted access to NEMO's API for billing purposes")
			return True
		return False
