from datetime import datetime, timedelta
from math import floor

from django.contrib.auth.decorators import login_required, permission_required
from django.db.models import QuerySet
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_GET

from NEMO.apps.sensors.customizations import SensorCustomization
from NEMO.apps.sensors.models import Sensor, SensorAlertLog, SensorCategory, SensorData
from NEMO.decorators import disable_session_expiry_refresh, postpone, staff_member_required
from NEMO.utilities import (
	BasicDisplayTable,
	beginning_of_the_day,
	export_format_datetime,
	extract_times,
	format_datetime,
)


@staff_member_required
@require_GET
def sensors(request, category_id=None):
	selected_category = None
	if category_id:
		selected_category = get_object_or_404(SensorCategory, pk=category_id)
	categories = SensorCategory.objects.filter(parent=category_id)
	sensor_list = Sensor.objects.filter(visible=True, sensor_category_id=category_id).order_by("name")
	return render(
		request,
		"sensors/sensors.html",
		{"selected_category": selected_category, "categories": categories, "sensors": sensor_list},
	)


@staff_member_required
@require_GET
def sensor_details(request, sensor_id, tab: str = None):
	sensor = get_object_or_404(Sensor, pk=sensor_id)
	chart_step = int(request.GET.get("chart_step", 1))
	default_refresh_rate = int(SensorCustomization.get("sensor_default_refresh_rate"))
	refresh_rate = int(request.GET.get("refresh_rate", default_refresh_rate))
	sensor_data, start, end = get_sensor_data(request, sensor)
	dictionary = {
		"tab": tab or "chart",
		"sensor": sensor,
		"start": start,
		"end": end,
		"refresh_rate": refresh_rate,
		"chart_step": chart_step,
	}
	return render(request, "sensors/sensor_data.html", dictionary)


@staff_member_required
@require_GET
def export_sensor_data(request, sensor_id):
	sensor = get_object_or_404(Sensor, pk=sensor_id)
	sensor_data, start, end = get_sensor_data(request, sensor)
	table_result = BasicDisplayTable()
	table_result.add_header(("date", "Date"))
	table_result.add_header(("value", "Value"))
	table_result.add_header(("display_value", "Display value"))
	for data_point in sensor_data:
		table_result.add_row(
			{
				"date": format_datetime(data_point.created_date, "SHORT_DATETIME_FORMAT"),
				"value": data_point.value,
				"display_value": data_point.display_value(),
			}
		)
	response = table_result.to_csv()
	sensor_name = slugify(sensor.name).replace("-", "_")
	filename = f"{sensor_name}_data_{export_format_datetime(start)}_to_{export_format_datetime(end)}.csv"
	response["Content-Disposition"] = f'attachment; filename="{filename}"'
	return response


@staff_member_required
@require_GET
@disable_session_expiry_refresh
def sensor_chart_data(request, sensor_id):
	sensor = get_object_or_404(Sensor, pk=sensor_id)
	labels = []
	data = []
	sensor_data = get_sensor_data(request, sensor)[0].order_by("created_date")
	for data_point in sensor_data:
		labels.append(format_datetime(data_point.created_date, "m/d/Y H:i:s"))
		data.append(data_point.value)
	return JsonResponse(data={"labels": labels, "data": data})


@staff_member_required
@require_GET
@disable_session_expiry_refresh
def sensor_alert_log(request, sensor_id):
	sensor = get_object_or_404(Sensor, pk=sensor_id)
	sensor_data, start, end = get_sensor_data(request, sensor)
	alert_log_entries = SensorAlertLog.objects.filter(sensor=sensor, time__gte=start, time__lte=end or timezone.now())
	return render(request, "sensors/sensor_alerts.html", {"alerts": alert_log_entries})


def get_sensor_data(request, sensor) -> (QuerySet, datetime, datetime):
	start, end = extract_times(request.GET, start_required=False, end_required=False)
	sensor_data = SensorData.objects.filter(sensor=sensor)
	now = timezone.now().replace(second=0, microsecond=0).astimezone()
	sensor_default_daterange = SensorCustomization.get("sensor_default_daterange")
	if not start:
		if sensor_default_daterange == "last_week":
			start = now - timedelta(weeks=1)
		elif sensor_default_daterange == "last_72hrs":
			start = now - timedelta(days=3)
		else:
			start = now - timedelta(days=1)
	return sensor_data.filter(created_date__gte=start, created_date__lte=(end or now)), start, end


@login_required
@require_GET
@permission_required("NEMO.trigger_timed_services", raise_exception=True)
def manage_sensor_data(request):
	return do_manage_sensor_data()


def do_manage_sensor_data(asynchronous=True):
	minute_of_the_day = floor((timezone.now() - beginning_of_the_day(timezone.now())).total_seconds() / 60)
	# Read data for each sensor at the minute interval set
	for sensor in Sensor.objects.exclude(read_frequency=0):
		if minute_of_the_day % sensor.read_frequency == 0:
			postpone(sensor.read_data)() if asynchronous else sensor.read_data()
	return HttpResponse()
