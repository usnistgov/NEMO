from NEMO.views.customization import get_customization


def show_logout_button(request):
	return {"logout_allowed": True}


def hide_logout_button(request):
	return {"logout_allowed": False}


def device(request):
	return {"device": request.device}


def facility_name(request):
	try:
		name = get_customization("facility_name")
	except:
		name = "Facility"
	return {"facility_name": name}
