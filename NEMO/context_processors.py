from NEMO.models import Area, Notification, PhysicalAccessLevel, Tool, User
from NEMO.utilities import (
    date_input_js_format,
    datetime_input_js_format,
    time_input_js_format,
    pickadate_date_format,
    pickadate_time_format,
)
from NEMO.views.customization import CustomizationBase
from NEMO.views.notifications import get_notification_counts


def show_logout_button(request):
    return {"logout_allowed": True}


def hide_logout_button(request):
    return {"logout_allowed": False}


def base_context(request):
    user: User = getattr(request, "user", None)
    customization_values = CustomizationBase.get_all()
    try:
        if "no_header" in request.GET:
            if request.GET["no_header"] == "True":
                request.session["no_header"] = True
            else:
                request.session["no_header"] = False
    except:
        request.session["no_header"] = False
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
        notification_counts = get_notification_counts(user)
    except:
        notification_counts = {}
    try:
        buddy_notification_count = notification_counts.get(Notification.Types.BUDDY_REQUEST, 0)
        buddy_notification_count += notification_counts.get(Notification.Types.BUDDY_REQUEST_REPLY, 0)
    except:
        buddy_notification_count = 0
    try:
        staff_assistance_notification_count = notification_counts.get(Notification.Types.STAFF_ASSISTANCE_REQUEST, 0)
        staff_assistance_notification_count += notification_counts.get(
            Notification.Types.STAFF_ASSISTANCE_REQUEST_REPLY, 0
        )
    except:
        staff_assistance_notification_count = 0
    try:
        temporary_access_notification_count = notification_counts.get(Notification.Types.TEMPORARY_ACCESS_REQUEST, 0)
    except:
        temporary_access_notification_count = 0
    try:
        adjustment_notification_count = notification_counts.get(Notification.Types.ADJUSTMENT_REQUEST, 0)
        adjustment_notification_count += notification_counts.get(Notification.Types.ADJUSTMENT_REQUEST_REPLY, 0)
    except:
        adjustment_notification_count = 0
    try:
        safety_notification_count = notification_counts.get(Notification.Types.SAFETY, 0)
    except:
        safety_notification_count = 0
    try:
        facility_managers_exist = User.objects.filter(is_active=True, is_facility_manager=True).exists()
    except:
        facility_managers_exist = False
    return {
        "customizations": customization_values,
        "facility_name": customization_values.get("facility_name"),
        "recurring_charges_name": customization_values.get("recurring_charges_name"),
        "site_title": customization_values.get("site_title"),
        "device": getattr(request, "device", "desktop"),
        "tools_exist": tools_exist,
        "areas_exist": areas_exist,
        "buddy_system_areas_exist": buddy_system_areas_exist,
        "access_user_request_allowed_exist": access_user_request_allowed_exist,
        "adjustment_request_allowed": customization_values.get("adjustment_requests_enabled", "") == "enabled",
        "staff_assistance_request_allowed": customization_values.get("staff_assistance_requests_enabled", "")
        == "enabled",
        "notification_counts": notification_counts,
        "buddy_notification_count": buddy_notification_count,
        "staff_assistance_notification_count": staff_assistance_notification_count,
        "temporary_access_notification_count": temporary_access_notification_count,
        "adjustment_notification_count": adjustment_notification_count,
        "safety_notification_count": safety_notification_count,
        "facility_managers_exist": facility_managers_exist,
        "time_input_js_format": time_input_js_format,
        "date_input_js_format": date_input_js_format,
        "datetime_input_js_format": datetime_input_js_format,
        "pickadate_date_format": pickadate_date_format,
        "pickadate_time_format": pickadate_time_format,
        "no_header": request.session.get("no_header", False),
        "safety_menu_item": customization_values.get("safety_main_menu") == "enabled",
        "calendar_page_title": customization_values.get("calendar_page_title"),
        "tool_control_page_title": customization_values.get("tool_control_page_title"),
        "status_dashboard_page_title": customization_values.get("status_dashboard_page_title"),
        "requests_page_title": customization_values.get("requests_page_title"),
        "safety_page_title": customization_values.get("safety_page_title"),
        "calendar_first_day_of_week": customization_values.get("calendar_first_day_of_week"),
        "allow_profile_view": customization_values.get("user_allow_profile_view", "") == "enabled",
    }
