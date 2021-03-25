from NEMO.models import Tool, Area, PhysicalAccessLevel, Notification
from NEMO.views.customization import get_customization
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
		facility_name = get_customization("facility_name")
	except:
		facility_name = "Facility"
	try:
		site_title = get_customization("site_title")
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
		notification_counts = get_notification_counts(request.user)
		buddy_notification_count = notification_counts.get(Notification.Types.BUDDY_REQUEST, 0)
		buddy_notification_count += notification_counts.get(Notification.Types.BUDDY_REQUEST_REPLY, 0)
	except:
		notification_counts = {}
		buddy_notification_count = 0
	return {
		"facility_name": facility_name,
		"site_title": site_title,
		"device": request.device,
		"tools_exist": tools_exist,
		"areas_exist": areas_exist,
		"buddy_system_areas_exist": buddy_system_areas_exist,
		"notification_counts": notification_counts,
		"buddy_notification_count": buddy_notification_count,
		"no_header": request.session.get("no_header", False),
	}
