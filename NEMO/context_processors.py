def show_logout_button(request):
	return {'logout_allowed': True}


def hide_logout_button(request):
	return {'logout_allowed': False}


def device(request):
	return {'device': request.device}
