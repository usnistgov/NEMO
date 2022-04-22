from datetime import datetime, timedelta
from math import floor

from django.contrib.auth.decorators import login_required, permission_required
from django.db.models import QuerySet
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_GET

from NEMO.apps.sensors.models import Sensor, SensorData
from NEMO.decorators import postpone, staff_member_required
from NEMO.utilities import (
	BasicDisplayTable,
	beginning_of_the_day,
	export_format_datetime,
	extract_times,
	format_datetime,
)


@staff_member_required
@require_GET
def sensors(request):
	sensor_list = Sensor.objects.filter(id__in=SensorData.objects.values_list("sensor", flat=True))
	sensor_list = sensor_list.order_by("sensor_category__name", "name")
	return render(request, "sensors/sensors.html", {"sensors": sensor_list})


@staff_member_required
@require_GET
def sensor_details(request, sensor_id, tab: str = None):
	sensor = get_object_or_404(Sensor, pk=sensor_id)
	chart_step = int(request.GET.get("chart_step", 1))
	return render(
		request, "sensors/sensor_data.html", {"tab": tab or "chart", "sensor": sensor, "chart_step": chart_step}
	)


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
		table_result.add_row({
			"date": format_datetime(data_point.created_date, "SHORT_DATETIME_FORMAT"),
			"value": data_point.value,
			"display_value": data_point.display_value()
		})
	response = table_result.to_csv()
	sensor_name = slugify(sensor.name).replace("-", "_")
	filename = f"{sensor_name}_data_{export_format_datetime(start)}_to_{export_format_datetime(end)}.csv"
	response["Content-Disposition"] = f'attachment; filename="{filename}"'
	return response


@staff_member_required
@require_GET
def sensor_chart_data(request, sensor_id):
	sensor = get_object_or_404(Sensor, pk=sensor_id)
	labels = []
	data = []
	sensor_data = get_sensor_data(request, sensor)[0].order_by("created_date")
	for data_point in sensor_data:
		labels.append(format_datetime(data_point.created_date, "m/d/Y H:i:s"))
		data.append(data_point.value)
	return JsonResponse(data={"labels": labels, "data": data})


def get_sensor_data(request, sensor) -> (QuerySet, datetime, datetime):
	start, end = extract_times(request.POST, start_required=False, end_required=False)
	sensor_data = SensorData.objects.filter(sensor=sensor)
	if not start:
		start = timezone.now() - timedelta(days=1)
	if not end:
		end = timezone.now()
	return sensor_data.filter(created_date__gte=start, created_date__lte=end), start, end


@login_required
@require_GET
@permission_required("NEMO.trigger_timed_services", raise_exception=True)
def manage_sensor_data(request):
	return do_manage_sensor_data()


def do_manage_sensor_data(asynchronous=True):
	minute_of_the_day = floor((timezone.now() - beginning_of_the_day(timezone.now())).total_seconds() / 60)
	# Read data for each sensor at the minute interval set
	for sensor in Sensor.objects.all():
		if minute_of_the_day % sensor.read_frequency == 0:
			postpone(sensor.read_data)() if asynchronous else sensor.read_data()
	return HttpResponse()
