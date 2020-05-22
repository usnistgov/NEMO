from django.conf.urls import url
from django.urls import path, include

from NEMO.apps.kiosk import views
from NEMO.views import area_access

urlpatterns = [
	# Tablet kiosk
	path('kiosk/', include([
		url(r'^occupancy/$', area_access.occupancy, name='kiosk_occupancy'),
		url(r'^enable_tool/$', views.enable_tool, name='enable_tool_from_kiosk'),
		url(r'^disable_tool/$', views.disable_tool, name='disable_tool_from_kiosk'),
		url(r'^reserve_tool/$', views.reserve_tool, name='reserve_tool_from_kiosk'),
		url(r'^cancel_reservation/(?P<reservation_id>\d+)/$', views.cancel_reservation,	name='cancel_reservation_from_kiosk'),
		url(r'^choices/$', views.choices, name='kiosk_choices'),
		url(r'^category_choices/(?P<category>.+)/(?P<user_id>\d+)/$', views.category_choices, name='kiosk_category_choices'),
		url(r'^tool_information/(?P<tool_id>\d+)/(?P<user_id>\d+)/(?P<back>back_to_start|back_to_category)/$', views.tool_information, name='kiosk_tool_information'),
		url(r'^tool_reservation/(?P<tool_id>\d+)/(?P<user_id>\d+)/(?P<back>back_to_start|back_to_category)/$', views.tool_reservation, name='kiosk_tool_reservation'),
		url(r'^(?P<location>.+)/$', views.kiosk, name='kiosk'),
		url(r'^$', views.kiosk, name='kiosk'),
	]))
]
