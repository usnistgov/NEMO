from NEMO.models import Tool, Area, PhysicalAccessLevel
from NEMO.views.customization import get_customization

def show_logout_button(request):
	return {"logout_allowed": True}


def hide_logout_button(request):
	return {"logout_allowed": False}


def base_context(request):
	try:
		if 'no_header' in request.GET:
			if request.GET['no_header'] == 'True':
				request.session['no_header'] = True
			else:
				request.session['no_header'] = False
	except:
		request.session['no_header'] = False
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
		areas_exist = Area.objects.filter(requires_reservation=True).exists() and PhysicalAccessLevel.objects.exists()
	except:
		areas_exist = False
	try:
		buddy_system_areas_exist = Area.objects.filter(buddy_system_allowed=True).exists()
	except:
		buddy_system_areas_exist = False
	return {
		"facility_name": facility_name,
		"site_title": site_title,
		"device": request.device,
		"tools_exist": tools_exist,
		"areas_exist": areas_exist,
		"buddy_system_areas_exist": buddy_system_areas_exist,
		"no_header": request.session.get('no_header', False),
	}
