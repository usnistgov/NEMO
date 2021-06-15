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
	Area,
	Resource,
	StaffCharge,
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
	AreaSerializer,
	ResourceSerializer,
	StaffChargeSerializer,
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
		"id": ["exact", "in"],
		"username": ["exact", "in"],
		"first_name": ["exact"],
		"last_name": ["exact"],
		"email": ["exact"],
		"badge_number": ["exact"],
		"is_active": ["exact"],
		"is_staff": ["exact"],
		"is_superuser": ["exact"],
		"is_service_personnel": ["exact"],
		"is_technician": ["exact"],
		"date_joined": ["month", "year", "gte", "gt", "lte", "lt"],
	}


class ProjectViewSet(ReadOnlyModelViewSet):
	queryset = Project.objects.all()
	serializer_class = ProjectSerializer
	filterset_fields = {
		"id": ["exact", "in"],
		"name": ["exact"],
		"application_identifier": ["exact"],
		"active": ["exact"],
		"account_id": ["exact", "in"],
	}


class AccountViewSet(ReadOnlyModelViewSet):
	queryset = Account.objects.all()
	serializer_class = AccountSerializer
	filterset_fields = {"id": ["exact", "in"], "name": ["exact"], "active": ["exact"]}


class ToolViewSet(ReadOnlyModelViewSet):
	queryset = Tool.objects.all()
	serializer_class = ToolSerializer
	filterset_fields = {
		"id": ["exact", "in"],
		"name": ["exact"],
		"visible": ["exact"],
		"_category": ["exact"],
		"_operational": ["exact"],
		"_location": ["exact"],
		"_requires_area_access": ["exact", "isnull"],
		"_post_usage_questions": ["isempty"],
	}


class AreaViewSet(ReadOnlyModelViewSet):
	queryset = Area.objects.all()
	serializer_class = AreaSerializer
	filterset_fields = {
		"id": ["exact", "in"],
		"name": ["exact"],
		"parent_area": ["exact", "in"],
		"category": ["exact"],
		"requires_reservation": ["exact"],
		"buddy_system_allowed": ["exact"],
		"maximum_capacity": ["exact", "gte", "gt", "lte", "lt", "isnull"],
		"count_staff_in_occupancy": ["exact"],
		"count_service_personnel_in_occupancy": ["exact"],
	}


class ResourceViewSet(ReadOnlyModelViewSet):
	queryset = Resource.objects.all()
	serializer_class = ResourceSerializer
	filterset_fields = {
		"id": ["exact", "in"],
		"name": ["exact"],
		"available": ["exact"],
		"fully_dependent_tools": ["in"],
		"partially_dependent_tools": ["in"],
		"dependent_areas": ["in"],
	}


class ReservationViewSet(ReadOnlyModelViewSet):
	queryset = Reservation.objects.all()
	serializer_class = ReservationSerializer
	filterset_fields = {
		"id": ["exact", "in"],
		"start": ["gte", "gt", "lte", "lt"],
		"end": ["gte", "gt", "lte", "lt", "isnull"],
		"project_id": ["exact", "in"],
		"user_id": ["exact", "in"],
		"creator_id": ["exact", "in"],
		"tool_id": ["exact", "in", "isnull"],
		"area_id": ["exact", "in", "isnull"],
		"cancelled": ["exact"],
		"missed": ["exact"],
		"question_data": ["isempty"],
	}


class UsageEventViewSet(ReadOnlyModelViewSet):
	queryset = UsageEvent.objects.all()
	serializer_class = UsageEventSerializer
	filterset_fields = {
		"id": ["exact", "in"],
		"start": ["gte", "gt", "lte", "lt"],
		"end": ["gte", "gt", "lte", "lt", "isnull"],
		"project_id": ["exact", "in"],
		"user_id": ["exact", "in"],
		"operator_id": ["exact", "in"],
		"tool_id": ["exact", "in"],
	}


class AreaAccessRecordViewSet(ReadOnlyModelViewSet):
	queryset = AreaAccessRecord.objects.all().order_by("-start")
	serializer_class = AreaAccessRecordSerializer
	filterset_fields = {
		"id": ["exact", "in"],
		"start": ["gte", "gt", "lte", "lt"],
		"end": ["gte", "gt", "lte", "lt", "isnull"],
		"project_id": ["exact", "in"],
		"customer_id": ["exact", "in"],
		"area_id": ["exact", "in"],
		"staff_charge_id": ["exact", "isnull", "in"],
	}


class TaskViewSet(ReadOnlyModelViewSet):
	queryset = Task.objects.all()
	serializer_class = TaskSerializer
	filterset_fields = {
		"id": ["exact", "in"],
		"urgency": ["exact", "gte", "gt", "lte", "lt"],
		"tool_id": ["exact", "in"],
		"force_shutdown": ["exact"],
		"safety_hazard": ["exact"],
		"creator_id": ["exact", "in"],
		"creation_time": ["gte", "gt", "lte", "lt"],
		"estimated_resolution_time": ["gte", "gt", "lte", "lt"],
		"problem_category": ["exact", "in"],
		"cancelled": ["exact"],
		"resolved": ["exact"],
		"resolution_time": ["gte", "gt", "lte", "lt"],
		"resolver_id": ["exact", "in"],
		"resolution_category": ["exact", "in"],
	}


class ScheduledOutageViewSet(ReadOnlyModelViewSet):
	queryset = ScheduledOutage.objects.all()
	serializer_class = ScheduledOutageSerializer
	filterset_fields = {
		"id": ["exact", "in"],
		"start": ["gte", "gt", "lte", "lt"],
		"end": ["gte", "gt", "lte", "lt", "isnull"],
		"creator_id": ["exact", "in"],
		"category": ["exact", "in"],
		"tool_id": ["exact", "in", "isnull"],
		"area_id": ["exact", "in", "isnull"],
		"resource_id": ["exact", "in", "isnull"],
	}


class StaffChargeViewSet(ReadOnlyModelViewSet):
	queryset = StaffCharge.objects.all()
	serializer_class = StaffChargeSerializer
	filterset_fields = {
		"id": ["exact", "in"],
		"staff_member_id": ["exact", "in"],
		"customer_id": ["exact", "in"],
		"project_id": ["exact", "in"],
		"start": ["gte", "gt", "lte", "lt"],
		"end": ["gte", "gt", "lte", "lt", "isnull"],
		"validated": ["exact"],
	}


class TrainingSessionViewSet(ReadOnlyModelViewSet):
	queryset = TrainingSession.objects.all()
	serializer_class = TrainingSessionSerializer
	filterset_fields = {
		"id": ["exact", "in"],
		"trainer_id": ["exact", "in"],
		"trainee_id": ["exact", "in"],
		"tool_id": ["exact", "in"],
		"project_id": ["exact", "in"],
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
