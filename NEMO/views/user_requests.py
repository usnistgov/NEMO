from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.http import require_GET

from NEMO.models import PhysicalAccessLevel, User
from NEMO.views.customization import get_customization


@login_required
@require_GET
def user_requests(request, tab: str = None):
	active_tab = (
		tab or "access"
		if PhysicalAccessLevel.objects.filter(allow_user_request=True).exists()
		   and User.objects.filter(is_active=True, is_facility_manager=True).exists()
		else "buddy"
	)
	buddy_requests_title = get_customization("buddy_requests_title")
	access_requests_title = get_customization("access_requests_title")
	dictionary = {
		"tab": active_tab,
		"buddy_requests_title": buddy_requests_title,
		"access_requests_title": access_requests_title,
	}
	return render(request, "requests/user_requests.html", dictionary)
