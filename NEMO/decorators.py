import importlib
import inspect
from functools import wraps
from threading import Lock, RLock, Thread

from django.contrib.auth import REDIRECT_FIELD_NAME
from django.contrib.auth.decorators import user_passes_test
from django.utils.text import slugify


def disable_session_expiry_refresh(f):
	"""
	Security policy dictates that the user's session should time out after a set duration.
	The user's session is automatically refreshed (that is, the expiration date
	of their session is moved forward to 30 minutes after the request time) whenever
	the user performs an action. Pages such as the Calendar, Tool Control, and Status Dashboard
	all have polling AJAX requests to update information on the page. These regular polling
	requests should not refresh the session (because it does not indicate the user took
	an action). Place this decorator on any view that is regularly polled so that the
	user's session is not refreshed.
	"""
	f.disable_session_expiry_refresh = True
	return f


# Use this decorator on a function to make a call to that function asynchronously
# The function will be run in a separate thread, and the current execution will continue
def postpone(function):
	def decorator(*arguments, **named_arguments):
		t = Thread(target=function, args=arguments, kwargs=named_arguments)
		t.daemon = True
		t.start()

	return decorator


# Use this decorator annotation to prevent concurrent execution of a function
# Passing a method argument will only lock a function being called with that same argument
# For example, @synchronized('tool_id') on a do_this(tool_id) function will only prevent do_this from being called
# at the same time with the same tool_id. If do_this is called twice with different tool_id, it won't be locked
def synchronized(method_argument=""):
	def inner(function):
		def decorator(*args, **kwargs):
			func_args = inspect.signature(function).bind(*args, **kwargs).arguments
			attribute_value = slugify(str(func_args.get(method_argument, ""))).replace("-", "_")
			lock_name = "__" + function.__name__ + "_lock_" + attribute_value + "__"
			lock: RLock = vars(function).get(lock_name, None)
			if lock is None:
				meta_lock = vars(decorator).setdefault("_synchronized_meta_lock", Lock())
				with meta_lock:
					lock = vars(function).get(lock_name, None)
					if lock is None:
						lock = RLock()
						setattr(function, lock_name, lock)
			with lock:
				return function(*args, **kwargs)

		return decorator

	return inner


# Use this decorator annotation to register your own customizations which will be shown in the customization page
# The key should be unique and if possible one word, the title will be shown on the customization tab
def customization(key, title, order=999):
	from NEMO.views.customization import CustomizationBase

	def customization_wrapper(customization_class):
		if not issubclass(customization_class, CustomizationBase):
			raise ValueError("Wrapped class must subclass CustomizationBase.")
		customization_instance = customization_class(key, title, order)
		CustomizationBase.add_instance(customization_instance)
		return customization_instance

	return customization_wrapper


# Utility function that returns a permission decorator based on the django user_passes_test decorator
# (see multiple examples below)
def permission_decorator(test_func):
	def decorator(view_func=None, redirect_field_name=REDIRECT_FIELD_NAME, login_url=None):
		actual_decorator = user_passes_test(
			test_func,
			login_url=login_url,
			redirect_field_name=redirect_field_name,
		)
		if view_func:
			return actual_decorator(view_func)
		return actual_decorator
	return decorator


administrator_required = permission_decorator(lambda u: u.is_active and u.is_superuser)
facility_manager_required = permission_decorator(lambda u: u.is_active and u.is_facility_manager)
staff_member_required = permission_decorator(lambda u: u.is_active and u.is_staff)
user_office_required = permission_decorator(lambda u: u.is_active and u.is_user_office)
accounting_required = permission_decorator(lambda u: u.is_active and u.is_accounting_officer)
staff_member_or_tool_superuser_required = permission_decorator(lambda u: u.is_active and (u.is_staff or u.is_tool_superuser))
staff_member_or_user_office_required = permission_decorator(lambda u: u.is_active and (u.is_staff or u.is_user_office))
accounting_or_user_office_or_manager_required = permission_decorator(lambda u: u.is_active and (u.is_accounting_officer or u.is_user_office or u.is_facility_manager))
user_office_or_facility_manager_required = permission_decorator(lambda u: u.is_active and (u.is_user_office or u.is_facility_manager))
any_staff_required = permission_decorator(lambda u: u.is_active and (u.is_staff or u.is_accounting_officer or u.is_user_office or u.is_facility_manager))


# Use this decorator annotation to replace another existing function. The first parameter of
# the new function should be "old_function" which will contain the function being replaced
# For example, to replace NEMO.views.policy.check_policy_to_save_reservation(arg1, arg2)
# @replace_function("NEMO.views.policy.check_policy_to_save_reservation")
# def new_function(old_function, arg1, arg2)
def replace_function(old_function_name):
	pkg, fun_name = old_function_name.rsplit(".", 1)
	pkg_mod = importlib.import_module(pkg)
	old_function = getattr(pkg_mod, fun_name)

	def decorator(function):
		@wraps(function)
		def wrapper(*args, **kwargs):
			return function(old_function, *args, **kwargs)

		setattr(pkg_mod, fun_name, wrapper)
		return wrapper

	return decorator
