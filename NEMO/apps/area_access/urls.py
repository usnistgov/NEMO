from django.conf.urls import url

from NEMO.apps.area_access import views
from NEMO.views import area_access

urlpatterns = [
	# Tablet area access
	url(r'^occupancy/$', area_access.occupancy, name='area_access_occupancy'),
	url(r'^welcome_screen/(?P<door_id>\d+)/$', views.welcome_screen, name='welcome_screen'),
	url(r'^farewell_screen/(?P<door_id>\d+)/$', views.farewell_screen, name='farewell_screen'),
	url(r'^login_to_area/(?P<door_id>\d+)/$', views.login_to_area, name='login_to_area'),
	url(r'^logout_of_area/(?P<door_id>\d+)/$', views.logout_of_area, name='logout_of_area'),
	url(r'^open_door/(?P<door_id>\d+)/$', views.open_door, name='open_door'),
]