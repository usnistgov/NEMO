from typing import List

from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.viewsets import ReadOnlyModelViewSet

from NEMO.filters import ReservationFilter, UsageEventFilter, AreaAccessRecordFilter, UserFilter
from NEMO.models import User, Project, Account, Reservation, UsageEvent, AreaAccessRecord, Task, ScheduledOutage, Tool
from NEMO.serializers import UserSerializer, ProjectSerializer, AccountSerializer, ReservationSerializer, \
	UsageEventSerializer, AreaAccessRecordSerializer, TaskSerializer, ScheduledOutageSerializer, ToolSerializer, \
	BillableItemSerializer
from NEMO.views.api_billing import BillableItem, BillingFilterForm, get_usage_events_for_billing, \
	get_area_access_for_billing, get_consumables_for_billing, get_missed_reservations_for_billing, \
	get_staff_charges_for_billing, get_training_sessions_for_billing

date_time_format = '%m/%d/%Y %H:%M:%S'


class UserViewSet(ReadOnlyModelViewSet):
	queryset = User.objects.all()
	serializer_class = UserSerializer
	filter_class = UserFilter


class ProjectViewSet(ReadOnlyModelViewSet):
	queryset = Project.objects.all()
	serializer_class = ProjectSerializer


class AccountViewSet(ReadOnlyModelViewSet):
	queryset = Account.objects.all()
	serializer_class = AccountSerializer


class ToolViewSet(ReadOnlyModelViewSet):
	queryset = Tool.objects.all()
	serializer_class = ToolSerializer


class ReservationViewSet(ReadOnlyModelViewSet):
	queryset = Reservation.objects.all()
	serializer_class = ReservationSerializer
	filter_class = ReservationFilter


class UsageEventViewSet(ReadOnlyModelViewSet):
	queryset = UsageEvent.objects.all()
	serializer_class = UsageEventSerializer
	filter_class = UsageEventFilter


class AreaAccessRecordViewSet(ReadOnlyModelViewSet):
	queryset = AreaAccessRecord.objects.all().order_by('-start')
	serializer_class = AreaAccessRecordSerializer
	filter_class = AreaAccessRecordFilter


class TaskViewSet(ReadOnlyModelViewSet):
	queryset = Task.objects.all()
	serializer_class = TaskSerializer


class ScheduledOutageViewSet(ReadOnlyModelViewSet):
	queryset = ScheduledOutage.objects.all()
	serializer_class = ScheduledOutageSerializer


@api_view(["GET"])
def billing(request):
	form = BillingFilterForm(request.GET)
	if not form.is_valid():
		return Response(status=status.HTTP_400_BAD_REQUEST, data=form.errors)

	data: List[BillableItem] = []
	data.extend(get_usage_events_for_billing(form))
	data.extend(get_area_access_for_billing(form))
	data.extend(get_consumables_for_billing(form))
	data.extend(get_missed_reservations_for_billing(form))
	data.extend(get_staff_charges_for_billing(form))
	data.extend(get_training_sessions_for_billing(form))

	serializer = BillableItemSerializer(data, many=True)
	return Response(serializer.data)
