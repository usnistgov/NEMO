from NEMO.views.customization import get_customization


def show_logout_button(request):
	return {"logout_allowed": True}


def hide_logout_button(request):
	return {"logout_allowed": False}


def base_context(request):
	try:
		facility_name = get_customization("facility_name")
	except:
		facility_name = "Facility"
	try:
		site_title = get_customization("site_title")
	except:
		site_title = ""
	return {
		"facility_name": facility_name,
		"site_title": site_title,
		"device": request.device
	}
