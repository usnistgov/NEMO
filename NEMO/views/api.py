from typing import List

from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.viewsets import ReadOnlyModelViewSet

from NEMO.models import (
	User,
	Project,
	Account,
	Reservation,
	UsageEvent,
	AreaAccessRecord,
	Task,
	ScheduledOutage,
	Tool,
	TrainingSession,
)
from NEMO.serializers import (
	UserSerializer,
	ProjectSerializer,
	AccountSerializer,
	ReservationSerializer,
	UsageEventSerializer,
	AreaAccessRecordSerializer,
	TaskSerializer,
	ScheduledOutageSerializer,
	ToolSerializer,
	BillableItemSerializer,
	TrainingSessionSerializer,
)
from NEMO.views.api_billing import (
	BillableItem,
	BillingFilterForm,
	get_usage_events_for_billing,
	get_area_access_for_billing,
	get_consumables_for_billing,
	get_missed_reservations_for_billing,
	get_staff_charges_for_billing,
	get_training_sessions_for_billing,
)

date_time_format = "%m/%d/%Y %H:%M:%S"


class UserViewSet(ReadOnlyModelViewSet):
	queryset = User.objects.all()
	serializer_class = UserSerializer
	filterset_fields = {
		"id": ["exact"],
		"username": ["exact"],
		"first_name": ["exact"],
		"last_name": ["exact"],
		"email": ["exact"],
		"badge_number": ["exact"],
		"is_active": ["exact"],
		"is_staff": ["exact"],
		"is_superuser": ["exact"],
		"is_service_personnel": ["exact"],
		"is_technician": ["exact"],
		"date_joined": ["month", "year"],
	}


class ProjectViewSet(ReadOnlyModelViewSet):
	queryset = Project.objects.all()
	serializer_class = ProjectSerializer
	filterset_fields = {
		"id": ["exact"],
		"name": ["exact"],
		"application_identifier": ["exact"],
		"active": ["exact"],
		"account_id": ["exact"],
	}


class AccountViewSet(ReadOnlyModelViewSet):
	queryset = Account.objects.all()
	serializer_class = AccountSerializer
	filterset_fields = {"id": ["exact"], "name": ["exact"], "active": ["exact"]}


class ToolViewSet(ReadOnlyModelViewSet):
	queryset = Tool.objects.all()
	serializer_class = ToolSerializer
	filterset_fields = {"id": ["exact"]}


class ReservationViewSet(ReadOnlyModelViewSet):
	queryset = Reservation.objects.all()
	serializer_class = ReservationSerializer
	filterset_fields = {
		"start": ["gte", "gt", "lte", "lt"],
		"end": ["gte", "gt", "lte", "lt", "isnull"],
		"project_id": ["exact"],
		"user_id": ["exact"],
		"creator_id": ["exact"],
		"tool_id": ["exact"],
		"area_id": ["exact"],
		"cancelled": ["exact"],
		"missed": ["exact"],
	}


class UsageEventViewSet(ReadOnlyModelViewSet):
	queryset = UsageEvent.objects.all()
	serializer_class = UsageEventSerializer
	filterset_fields = {
		"start": ["gte", "gt", "lte", "lt"],
		"end": ["gte", "gt", "lte", "lt", "isnull"],
		"project_id": ["exact"],
		"user_id": ["exact"],
		"operator_id": ["exact"],
		"tool_id": ["exact"],
	}


class AreaAccessRecordViewSet(ReadOnlyModelViewSet):
	queryset = AreaAccessRecord.objects.all().order_by("-start")
	serializer_class = AreaAccessRecordSerializer
	filterset_fields = {
		"start": ["gte", "gt", "lte", "lt"],
		"end": ["gte", "gt", "lte", "lt", "isnull"],
		"project_id": ["exact"],
		"customer_id": ["exact"],
		"area_id": ["exact"],
		"staff_charge_id": ["exact", "isnull"],
	}


class TaskViewSet(ReadOnlyModelViewSet):
	queryset = Task.objects.all()
	serializer_class = TaskSerializer


class ScheduledOutageViewSet(ReadOnlyModelViewSet):
	queryset = ScheduledOutage.objects.all()
	serializer_class = ScheduledOutageSerializer


class TrainingSessionViewSet(ReadOnlyModelViewSet):
	queryset = TrainingSession.objects.all()
	serializer_class = TrainingSessionSerializer
	filterset_fields = {
		"trainer_id": ["exact"],
		"trainee_id": ["exact"],
		"tool_id": ["exact"],
		"project_id": ["exact"],
		"duration": ["exact", "gte", "lte", "gt", "lt"],
		"type": ["exact", "in"],
		"date": ["gte", "gt", "lte", "lt"],
		"qualified": ["exact"],
	}


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
