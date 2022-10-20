from django.urls import include, path, re_path

from NEMO.apps.kiosk import views
from NEMO.views import area_access

urlpatterns = [
	# Tablet kiosk
	path("kiosk/", include([
		path("occupancy/", area_access.occupancy, name="kiosk_occupancy"),
		path("enable_tool/", views.enable_tool, name="enable_tool_from_kiosk"),
		path("disable_tool/", views.disable_tool, name="disable_tool_from_kiosk"),
		path("reserve_tool/", views.reserve_tool, name="reserve_tool_from_kiosk"),
		path("cancel_reservation/<int:reservation_id>/", views.cancel_reservation,	name="cancel_reservation_from_kiosk"),
		path("choices/", views.choices, name="kiosk_choices"),
		path("category_choices/<str:category>/<int:user_id>/", views.category_choices, name="kiosk_category_choices"),
		re_path(r"^tool_information/(?P<tool_id>\d+)/(?P<user_id>\d+)/(?P<back>back_to_start|back_to_category)/$", views.tool_information, name="kiosk_tool_information"),
		re_path(r"^tool_reservation/(?P<tool_id>\d+)/(?P<user_id>\d+)/(?P<back>back_to_start|back_to_category)/$", views.tool_reservation, name="kiosk_tool_reservation"),
		re_path(r"^(?P<location>.+)/$", views.kiosk, name="kiosk"),
		path("", views.kiosk, name="kiosk"),
	]))
]
