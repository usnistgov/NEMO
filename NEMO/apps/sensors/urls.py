from django.urls import path

from NEMO.apps.sensors import views

urlpatterns = [
	path("sensors/", views.sensors, name="sensors"),
	path("sensor_details/<int:sensor_id>/", views.sensor_details, name="sensor_details"),
	path("sensor_chart_data/<int:sensor_id>/", views.sensor_chart_data, name="sensor_chart_data"),
	path("manage_sensor_data/", views.manage_sensor_data, name="manage_sensor_data"),
]
