from NEMO.models import Area, Notification, PhysicalAccessLevel, Tool, User
from NEMO.utilities import date_input_js_format, datetime_input_js_format, time_input_js_format
from NEMO.views.customization import ApplicationCustomization, RecurringChargesCustomization, SafetyCustomization
from NEMO.views.notifications import get_notification_counts


def show_logout_button(request):
	return {"logout_allowed": True}


def hide_logout_button(request):
	return {"logout_allowed": False}


def base_context(request):
	try:
		if "no_header" in request.GET:
			if request.GET["no_header"] == "True":
				request.session["no_header"] = True
			else:
				request.session["no_header"] = False
	except:
		request.session["no_header"] = False
	try:
		facility_name = ApplicationCustomization.get("facility_name")
	except:
		facility_name = "Facility"
	try:
		recurring_charges_name = RecurringChargesCustomization.get("recurring_charges_name")
	except:
		recurring_charges_name = "Recurring charges"
	try:
		site_title = ApplicationCustomization.get("site_title")
	except:
		site_title = ""
	try:
		tools_exist = Tool.objects.filter(visible=True).exists()
	except:
		tools_exist = False
	try:
		areas_exist = Area.objects.exists() and PhysicalAccessLevel.objects.exists()
	except:
		areas_exist = False
	try:
		buddy_system_areas_exist = Area.objects.filter(buddy_system_allowed=True).exists()
	except:
		buddy_system_areas_exist = False
	try:
		access_user_request_allowed_exist = PhysicalAccessLevel.objects.filter(allow_user_request=True).exists()
	except:
		access_user_request_allowed_exist = False
	try:
		notification_counts = get_notification_counts(request.user)
	except:
		notification_counts = {}
	try:
		buddy_notification_count = notification_counts.get(Notification.Types.BUDDY_REQUEST, 0)
		buddy_notification_count += notification_counts.get(Notification.Types.BUDDY_REQUEST_REPLY, 0)
	except:
		buddy_notification_count = 0
	try:
		temporary_access_notification_count = notification_counts.get(Notification.Types.TEMPORARY_ACCESS_REQUEST, 0)
	except:
		temporary_access_notification_count = 0
	try:
		safety_notification_count = notification_counts.get(Notification.Types.SAFETY, 0)
	except:
		safety_notification_count = 0
	try:
		facility_managers_exist = User.objects.filter(is_active=True, is_facility_manager=True).exists()
	except:
		facility_managers_exist = False
	try:
		safety_menu_item = SafetyCustomization.get_bool("safety_main_menu")
	except:
		safety_menu_item = True
	return {
		"facility_name": facility_name,
		"recurring_charges_name": recurring_charges_name,
		"site_title": site_title,
		"device": getattr(request, "device", "desktop"),
		"tools_exist": tools_exist,
		"areas_exist": areas_exist,
		"buddy_system_areas_exist": buddy_system_areas_exist,
		"access_user_request_allowed_exist": access_user_request_allowed_exist,
		"notification_counts": notification_counts,
		"buddy_notification_count": buddy_notification_count,
		"temporary_access_notification_count": temporary_access_notification_count,
		"safety_notification_count": safety_notification_count,
		"facility_managers_exist": facility_managers_exist,
		"time_input_js_format": time_input_js_format,
		"date_input_js_format": date_input_js_format,
		"datetime_input_js_format": datetime_input_js_format,
		"no_header": request.session.get("no_header", False),
		"safety_menu_item": safety_menu_item,
	}
