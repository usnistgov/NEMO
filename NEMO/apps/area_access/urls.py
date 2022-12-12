from django.urls import path

from NEMO.apps.area_access import views
from NEMO.views import area_access

urlpatterns = [
	# Tablet area access
	path("occupancy/", area_access.occupancy, name="area_access_occupancy"),
	path("welcome_screen/<int:door_id>/", views.welcome_screen, name="welcome_screen"),
	path("farewell_screen/<int:door_id>/", views.farewell_screen, name="farewell_screen"),
	path("login_to_area/<int:door_id>/", views.login_to_area, name="login_to_area"),
	path("logout_of_area/<int:door_id>/", views.logout_of_area, name="logout_of_area"),
	path("open_door/<int:door_id>/", views.open_door, name="open_door"),
]