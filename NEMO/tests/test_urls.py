import ast
import datetime
import importlib
import inspect
from _ast import FunctionDef, Module
from logging import getLogger
from typing import List

from django.conf import settings
from django.core.management import call_command
from django.test.client import RequestFactory
from django.test.testcases import TestCase
from django.urls import reverse
from django.urls.resolvers import RegexPattern

from NEMO.models import User
from NEMO.tests.test_utilities import login_as, login_as_staff, login_as_user, login_as_user_with_permissions
from NEMO.utilities import get_full_url
from NEMO.views.customization import ApplicationCustomization

url_test_logger = getLogger(__name__)

start = datetime.datetime.now()
end_one_day = start + datetime.timedelta(days=1)

url_kwargs_get_post = {
	"impersonate": {"login_id": 1},
	"cancel_reservation_from_kiosk": {"kwargs": {"reservation_id": 1}, "post": {"customer_id": 1}},
	"kiosk_category_choices": {"kwargs": {"category": "test", "user_id": 1}},
	"kiosk_tool_information": {"kwargs": {"tool_id": 1, "user_id": 1, "back": "back_to_start"}},
	"enable_tool_from_kiosk": {"post": {"tool_id": 1, "customer_id": 1, "project_id": 1}},
	"disable_tool_from_kiosk": {"post": {"tool_id": 1, "customer_id": 1}},
	"reserve_tool_from_kiosk": {"post": {"tool_id": 1, "customer_id": 1, "project_id": 1, "back": ""}},
	"login_to_area": {"kwargs": {"door_id": 1}, "post": {"badge_number": 1}},
	"logout_of_area": {"kwargs": {"door_id": 1}, "post": {"badge_number": 1}},
	"open_door": {"kwargs": {"door_id": 1}, "post": {"badge_number": 1}},
	"sensor_details": {"kwargs": {"sensor_id": 1}},
	"get_projects": {"get": {"user_id": 1}},
	"get_projects_for_tool_control": {"get": {"user_id": 1}},
	"tool_control": {"kwargs": {"tool_id": 1}},
	"tool_configuration": {"login_id": 1, "post": {"configuration_id": 1, "slot": 0, "choice": 1}},
	"tool_usage_group_question": {"get": {"index": 1, "virtual_inputs": 1}},
	"user_requests": {"kwargs": {}},
	"delete_access_request": {"login_id": 3, "kwargs": {"request_id": 1}},
	"edit_buddy_request": {"login_id": 3, "kwargs": {"request_id": 1}},
	"delete_buddy_request": {"login_id": 3, "kwargs": {"request_id": 1}},
	"buddy_request_reply": {"login_id": 1, "kwargs": {"request_id": 1}, "post": {"reply_content": "test"}},
	"create_comment": {"post": {"tool": 1, "content": "test comment", "expiration": "0"}},
	"past_comments_and_tasks": {
		"get": {"tool_id": 1, "search": "test", "start": start.timestamp(), "end": end_one_day.timestamp()}
	},
	"calendar": {"kwargs": {}},
	"event_feed": {
		"get": {
			"event_type": "reservations",
			"start": start.strftime("%Y-%m-%d"),
			"end": end_one_day.strftime("%Y-%m-%d"),
			"item_type": "tool",
			"item_id": 1,
			"personal_schedule": "yes",
		}
	},
	"reservation_group_question": {"get": {"index": 1, "virtual_inputs": 1}},
	"status_dashboard_tab": {"kwargs": {"tab": "tools"}},
	"modify_qualifications": {"post": {"action": "qualify", "chosen_user": 1, "chosen_tool": 1}},
	"get_qualified_users": {"get": {"tool_id": 1}},
	"begin_staff_charge": {"post": {"customer": 1, "project": 1}},
	"begin_staff_area_charge": {"post": {"area": 1}},
	"refresh_sidebar_icons": {"kwargs": {}},
	"get_email_form": {"get": {"recipient": "captain.nemo@nautilus.com"}},
	"send_email": {"post": {"recipient": "captain.nemo@nautilus.com", "subject": "test subject"}},
	"email_broadcast": {"kwargs": {"audience": "tool"}},
	"email_preview": {
		"post": {"title": "test title", "greeting": "test greeting", "contents": "test content", "color": "red"}
	},
	"maintenance": {"kwargs": {}},
	"training_entry": {"get": {"entry_number": 1}},
	"choose_item": {"kwargs": {"next_page": "view_calendar"}},
	"view_calendar": {"kwargs": {"item_type": "tool", "item_id": 1}},
	"calendar_self_log_in": {"login_id": 2, "post": {"area": 1, "project": 1}},
	"force_area_logout": {"kwargs": {"user_id": 2}},
	"self_log_in": {"login_id": 2},
	"self_log_out": {"kwargs": {"user_id": 2}},
	"publish_new_news": {"post": {"title": "test title", "content": "test_content"}},
	"publish_news_update": {"post": {"update": "test update"}},
	"user_drill_down": {
		"get": {
			"user": 1,
			"target": "tool|1",
			"start": start.strftime(settings.DATE_INPUT_FORMATS[0]),
			"end": end_one_day.strftime(settings.DATE_INPUT_FORMATS[0]),
		}
	},
	"toggle_active": {"kwargs": {"kind": "project", "identifier": 3}},
	"remove_user_from_project": {"post": {"user_id": 3, "project_id": 3}},
	"add_user_to_project": {"post": {"user_id": 3, "project_id": 3}},
	"history": {"kwargs": {"item_type": "user", "item_id": 1}},
	"customization": {"kwargs": {"key": "application"}},
	"customize": {"kwargs": {"key": "application"}, "post": {"facility_name": "test facility"}},
}

urls_to_skip = [
	"kiosk_tool_reservation",
	"cancel_reservation_from_kiosk",
	"create_reservation",
	"resize_reservation",
	"move_reservation",
	"cancel_reservation",
	"change_reservation_project",
	"create_outage",
	"resize_outage",
	"move_outage",
	"cancel_outage",
	"reset_tool_counter",
	"update_safety_issue",
	"new_reservation",
]


class URLsTestCase(TestCase):
	@classmethod
	def setUpTestData(cls):
		call_command("loaddata", "resources/fixtures/splash_pad.json", app_label="NEMO")

	def test_get_full_url(self):
		request = RequestFactory().get("/")
		location = reverse("create_or_modify_user", args=[1])
		# Test client request defaults to http://testserver
		self.assertEqual(get_full_url(location, request), "http://testserver/user/1/")
		self.assertEqual(get_full_url(location), "/user/1/")
		settings.MAIN_URL = "https://nemo.nist.gov"
		self.assertEqual(get_full_url(location), "https://nemo.nist.gov/user/1/")
		settings.MAIN_URL = "https://nemo.nist.gov/"
		self.assertEqual(get_full_url(location), "https://nemo.nist.gov/user/1/")
		settings.MAIN_URL = "https://nemo.nist.gov:8000"
		self.assertEqual(get_full_url(location), "https://nemo.nist.gov:8000/user/1/")

	def test_urls(self):
		module = importlib.import_module(settings.ROOT_URLCONF)
		test_urls(self, module.urlpatterns, url_kwargs_get_post, urls_to_skip)

	def test_more_calendar_urls(self):
		facility_name = ApplicationCustomization.get("facility_name")
		test_url(
			self,
			"event_feed",
			{
				"get": {
					"event_type": f"{facility_name.lower()} usage",
					"start": start.strftime("%Y-%m-%d"),
					"end": end_one_day.strftime("%Y-%m-%d"),
					"item_type": "tool",
					"item_id": 1,
				}
			},
		)
		test_url(
			self,
			"event_feed",
			{
				"get": {
					"event_type": f"{facility_name.lower()} usage",
					"start": start.strftime("%Y-%m-%d"),
					"end": end_one_day.strftime("%Y-%m-%d"),
					"personal_schedule": "yes",
				}
			},
		)
		test_url(
			self,
			"event_feed",
			{
				"get": {
					"event_type": f"{facility_name.lower()} usage",
					"start": start.strftime("%Y-%m-%d"),
					"end": end_one_day.strftime("%Y-%m-%d"),
					"all_tools": "yes",
				}
			},
		)
		test_url(
			self,
			"event_feed",
			{
				"get": {
					"event_type": f"{facility_name.lower()} usage",
					"start": start.strftime("%Y-%m-%d"),
					"end": end_one_day.strftime("%Y-%m-%d"),
					"all_areas": "yes",
				}
			},
		)
		test_url(
			self,
			"event_feed",
			{
				"get": {
					"event_type": f"{facility_name.lower()} usage",
					"start": start.strftime("%Y-%m-%d"),
					"end": end_one_day.strftime("%Y-%m-%d"),
					"all_areastools": "yes",
				}
			},
		)
		test_url(
			self,
			"event_feed",
			{
				"login_id": 1,
				"get": {
					"event_type": "specific user",
					"user": 3,
					"start": start.strftime("%Y-%m-%d"),
					"end": end_one_day.strftime("%Y-%m-%d"),
				},
			},
		)


def test_url(test_case, name, url_params):
	module = importlib.import_module(settings.ROOT_URLCONF)
	url_pattern = [url_patt for url_patt in module.urlpatterns if hasattr(url_patt, "name") and url_patt.name == name]
	test_urls(test_case, url_pattern, {name: url_params}, [])


def test_urls(test_case, url_patterns, url_params, url_skip, prefix=""):
	for pattern in url_patterns:
		if hasattr(pattern, "url_patterns"):
			# this is an included urlconf
			new_prefix = prefix
			if pattern.namespace:
				new_prefix = prefix + (":" if prefix else "") + pattern.namespace
			test_urls(test_case, pattern.url_patterns, url_params, url_skip, prefix=new_prefix)
		else:
			try:
				pkg, fun_name = pattern.lookup_str.rsplit(".", 1)
				if pkg in [
					"NEMO.decorators.synchronized",
					"django.contrib.admin.sites",
					"django.contrib.admin.options",
				]:
					continue
				pkg_mod = importlib.import_module(pkg)
				view_function = getattr(pkg_mod, fun_name)

				module_def: Module = ast.parse(inspect.getsource(view_function))
				function_def = next(iter(module_def.body))

				# Only test urls without parameters and with a name for reverse
				# if pattern.pattern.regex.groups == 0 and hasattr(pattern, "name") and pattern.name:
				if hasattr(pattern, "name") and pattern.name:
					name = pattern.name
					fullname = (prefix + ":" + name) if prefix else name
					# Check if we should skip this URL
					if fullname in url_skip:
						continue
					user, kwargs_params, get_params, post_params = get_all_params(fullname, url_params, pattern.pattern)
					url = reverse(fullname, kwargs=kwargs_params)
					annotations = get_annotations(function_def)
					# Login depending on annotation
					if user:
						login_as(test_case.client, user)
					else:
						login_as_relevant_user(test_case, annotations)
					if "require_GET" in annotations:
						response = test_case.client.get(url, data=get_params, follow=True)
						test_case.assertEqual(response.status_code, 200, msg=f"wrong status code for {fullname}")
					if "require_POST" in annotations:
						response = test_case.client.post(url, data=post_params, follow=True)
						test_case.assertEqual(response.status_code, 200, msg=f"wrong status code for {fullname}")
			except ModuleNotFoundError as mnfe:
				url_test_logger.warning(mnfe)
			except Exception as e:
				raise Exception(f"error with url: {fullname if 'fullname' in locals() else 'no_url'}") from e


def get_annotations(function_def: FunctionDef) -> List[str]:
	annotations = []
	for n in function_def.decorator_list:
		if isinstance(n, ast.Call):
			name = n.func.attr if isinstance(n.func, ast.Attribute) else n.func.id
		else:
			name = n.attr if isinstance(n, ast.Attribute) else n.id
		if name == "require_http_methods" and "GET" in [arg.s for arg in n.args[0].elts]:
			name = "require_GET"
		elif name == "require_http_methods" and "POST" in [arg.s for arg in n.args[0].elts]:
			name = "require_POST"
		elif name == "permission_required" and "NEMO.trigger_timed_services" == n.args[0].s:
			name = "time_services_required"
		elif name == "permission_required" and n.args[0].s == "NEMO.kiosk":
			name = "kiosk_required"
		elif name == "permission_required" and n.args[0].s == "NEMO.kiosk":
			name = "kiosk_required"
		elif name == "permission_required" and n.args[0].s in [
			"NEMO.change_areaaccessrecord",
			"NEMO.add_areaaccessrecord",
		]:
			name = "area_access_required"
		annotations.append(name)
	return annotations


def login_as_relevant_user(test_case: TestCase, annotations: List[str]):
	if "time_services_required" in annotations:
		login_as_user_with_permissions(test_case.client, ["trigger_timed_services"])
	elif "kiosk_required" in annotations:
		login_as_user_with_permissions(test_case.client, ["kiosk"])
	elif "area_access_required" in annotations:
		login_as_user_with_permissions(test_case.client, ["add_areaaccessrecord", "change_areaaccessrecord"])
	elif "login_required" in annotations:
		login_as_user(test_case.client)
	elif "staff_member_required" in annotations or "staff_member_or_tool_superuser_required" in annotations:
		login_as_staff(test_case.client)
	elif "administrator_required" in annotations:
		staff = login_as_staff(test_case.client)
		staff.is_superuser = True
		staff.save()
		login_as(test_case.client, staff)
	elif "facility_manager_required" in annotations:
		staff = login_as_staff(test_case.client)
		staff.is_facility_manager = True
		staff.save()
		login_as(test_case.client, staff)


def get_all_params(url: str, url_parameters: dict, pattern: RegexPattern) -> (dict, dict, dict):
	url_params = url_parameters.get(url, {})
	user = User.objects.get(pk=url_params.get("login_id")) if "login_id" in url_params else None
	kwargs = url_params.get("kwargs", None)
	# Try to fill regex groups with ones, since most test data has id 1
	if kwargs is None and pattern.regex.groups:
		kwargs = {x: 1 for x in pattern.regex.groupindex}
	return user, kwargs, url_params.get("get", {}), url_params.get("post", {})
