from typing import List

from drf_excel.mixins import XLSXFileMixin
from rest_framework import status
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet, ReadOnlyModelViewSet

from NEMO.models import (
	Account,
	AccountType,
	Area,
	AreaAccessRecord,
	Project,
	Reservation,
	Resource,
	ScheduledOutage,
	StaffCharge,
	Task,
	Tool,
	TrainingSession,
	UsageEvent,
	User,
)
from NEMO.serializers import (
	AccountSerializer,
	AccountTypeSerializer,
	AreaAccessRecordSerializer,
	AreaSerializer,
	BillableItemSerializer,
	ProjectSerializer,
	ReservationSerializer,
	ResourceSerializer,
	ScheduledOutageSerializer,
	StaffChargeSerializer,
	TaskSerializer,
	ToolSerializer,
	TrainingSessionSerializer,
	UsageEventSerializer,
	UserSerializer,
)
from NEMO.utilities import export_format_datetime
from NEMO.views.api_billing import (
	BillableItem,
	BillingFilterForm,
	get_area_access_for_billing,
	get_consumables_for_billing,
	get_missed_reservations_for_billing,
	get_staff_charges_for_billing,
	get_training_sessions_for_billing,
	get_usage_events_for_billing,
)


class UserViewSet(XLSXFileMixin, ReadOnlyModelViewSet):
	queryset = User.objects.all()
	serializer_class = UserSerializer
	filterset_fields = {
		"id": ["exact", "in"],
		"type": ["exact", "in"],
		"domain": ["exact", "in", "isempty"],
		"username": ["exact", "in"],
		"first_name": ["exact", "icontains"],
		"last_name": ["exact", "icontains"],
		"email": ["exact", "icontains"],
		"badge_number": ["exact"],
		"is_active": ["exact"],
		"is_staff": ["exact"],
		"is_facility_manager": ["exact"],
		"is_superuser": ["exact"],
		"is_service_personnel": ["exact"],
		"is_technician": ["exact"],
		"training_required": ["exact"],
		"date_joined": ["month", "year", "gte", "gt", "lte", "lt"],
		"last_login": ["month", "year", "gte", "gt", "lte", "lt", "isnull"],
		"access_expiration": ["month", "year", "gte", "gt", "lte", "lt", "isnull"],
	}

	def get_filename(self, *args, **kwargs):
		return f"users-{export_format_datetime()}.xlsx"


class ProjectViewSet(XLSXFileMixin, ReadOnlyModelViewSet):
	queryset = Project.objects.all()
	serializer_class = ProjectSerializer
	filterset_fields = {
		"id": ["exact", "in"],
		"name": ["exact"],
		"application_identifier": ["exact"],
		"active": ["exact"],
		"account_id": ["exact", "in"],
	}

	def get_filename(self, *args, **kwargs):
		return f"projects-{export_format_datetime()}.xlsx"


class AccountTypeViewSet(XLSXFileMixin, ReadOnlyModelViewSet):
	queryset = AccountType.objects.all()
	serializer_class = AccountTypeSerializer
	filterset_fields = {"id": ["exact", "in"], "name": ["exact"], "display_order": ["exact"]}

	def get_filename(self, *args, **kwargs):
		return f"account_types-{export_format_datetime()}.xlsx"


class AccountViewSet(XLSXFileMixin, ReadOnlyModelViewSet):
	queryset = Account.objects.all()
	serializer_class = AccountSerializer
	filterset_fields = {"id": ["exact", "in"], "name": ["exact"], "active": ["exact"]}

	def get_filename(self, *args, **kwargs):
		return f"accounts-{export_format_datetime()}.xlsx"


class ToolViewSet(XLSXFileMixin, ReadOnlyModelViewSet):
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

	def get_filename(self, *args, **kwargs):
		return f"tools-{export_format_datetime()}.xlsx"


class AreaViewSet(XLSXFileMixin, ReadOnlyModelViewSet):
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

	def get_filename(self, *args, **kwargs):
		return f"areas-{export_format_datetime()}.xlsx"


class ResourceViewSet(XLSXFileMixin, ReadOnlyModelViewSet):
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

	def get_filename(self, *args, **kwargs):
		return f"resources-{export_format_datetime()}.xlsx"


class ReservationViewSet(XLSXFileMixin, ReadOnlyModelViewSet):
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

	def get_filename(self, *args, **kwargs):
		return f"reservations-{export_format_datetime()}.xlsx"


class UsageEventViewSet(XLSXFileMixin, ReadOnlyModelViewSet):
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

	def get_filename(self, *args, **kwargs):
		return f"usage_events-{export_format_datetime()}.xlsx"


class AreaAccessRecordViewSet(XLSXFileMixin, ReadOnlyModelViewSet):
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

	def get_filename(self, *args, **kwargs):
		return f"area_access_records-{export_format_datetime()}.xlsx"


class TaskViewSet(XLSXFileMixin, ReadOnlyModelViewSet):
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

	def get_filename(self, *args, **kwargs):
		return f"tasks-{export_format_datetime()}.xlsx"


class ScheduledOutageViewSet(XLSXFileMixin, ReadOnlyModelViewSet):
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

	def get_filename(self, *args, **kwargs):
		return f"outages-{export_format_datetime()}.xlsx"


class StaffChargeViewSet(XLSXFileMixin, ReadOnlyModelViewSet):
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
		"note": ["contains"],
	}

	def get_filename(self, *args, **kwargs):
		return f"staff_charges-{export_format_datetime()}.xlsx"


class TrainingSessionViewSet(XLSXFileMixin, ReadOnlyModelViewSet):
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

	def get_filename(self, *args, **kwargs):
		return f"training_sessions-{export_format_datetime()}.xlsx"


class BillingViewSet(XLSXFileMixin, GenericViewSet):
	serializer_class = BillableItemSerializer

	def list(self, request, *args, **kwargs):
		billing_form = BillingFilterForm(self.request.GET)
		if not billing_form.is_valid():
			return Response(status=status.HTTP_400_BAD_REQUEST, data=billing_form.errors)
		queryset = self.get_queryset()
		serializer = self.serializer_class(queryset, many=True)
		return Response(serializer.data)

	def check_permissions(self, request):
		if not request or not request.user.has_perm('NEMO.use_billing_api'):
			self.permission_denied(request)

	def get_queryset(self):
		billing_form = BillingFilterForm(self.request.GET)
		billing_form.full_clean()
		data: List[BillableItem] = []
		data.extend(get_usage_events_for_billing(billing_form))
		data.extend(get_area_access_for_billing(billing_form))
		data.extend(get_consumables_for_billing(billing_form))
		data.extend(get_missed_reservations_for_billing(billing_form))
		data.extend(get_staff_charges_for_billing(billing_form))
		data.extend(get_training_sessions_for_billing(billing_form))

		data.sort(key=lambda x: x.start, reverse=True)
		return data

	def get_filename(self, *args, **kwargs):
		return f"billing-{export_format_datetime()}.xlsx"
