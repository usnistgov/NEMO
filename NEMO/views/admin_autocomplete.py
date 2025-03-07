from functools import update_wrapper

from django.apps import apps
from django.contrib.admin.views.autocomplete import AutocompleteJsonView
from django.core.exceptions import PermissionDenied


class AutocompleteViewWithFixedPermissions(AutocompleteJsonView):
    def has_perm(self, request, obj=None):
        # First let's get the source admin, NOT the related field admin
        try:
            app_label = request.GET["app_label"]
            model_name = request.GET["model_name"]
        except KeyError as e:
            raise PermissionDenied from e
        try:
            source_model = apps.get_model(app_label, model_name)
        except LookupError as e:
            raise PermissionDenied from e
        try:
            model_admin = self.admin_site._registry[source_model]
        except KeyError as e:
            raise PermissionDenied from e

        """
        Now instead of checking if the user has view permission on the related model, 
        we are simply checking if he has add or change permission on the source model
        """
        return model_admin.has_add_permission(request) or model_admin.has_change_permission(request, obj=obj)


def as_view(admin_site):

    def wrap(view, cacheable=False):
        def wrapper(*args, **kwargs):
            return admin_site.admin_view(view, cacheable)(*args, **kwargs)

        wrapper.admin_site = admin_site
        return update_wrapper(wrapper, view)

    def autocomplete_view(request):
        return AutocompleteViewWithFixedPermissions.as_view(admin_site=admin_site)(request)

    return wrap(autocomplete_view)
