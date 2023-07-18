from typing import List

from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.utils.safestring import mark_safe
from drf_excel.mixins import XLSXFileMixin
from rest_framework import status, viewsets
from rest_framework.renderers import BrowsableAPIRenderer
from rest_framework.response import Response
from rest_framework.serializers import ListSerializer

from NEMO.models import (
	Account,
	AccountType,
	Area,
	AreaAccessRecord,
	Consumable,
	ConsumableCategory,
	ConsumableWithdraw,
	Project,
	ProjectDiscipline,
	Qualification,
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
	ConsumableCategorySerializer,
	ConsumableSerializer,
	ConsumableWithdrawSerializer,
	ContentTypeSerializer,
	GroupSerializer,
	PermissionSerializer,
	ProjectDisciplineSerializer,
	ProjectSerializer,
	QualificationSerializer,
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


class SingleInstanceHTMLFormBrowsableAPIRenderer(BrowsableAPIRenderer):
	"""
	This implementation of the BrowsableAPIRenderer prevents it from throwing
	errors while a list of data is sent to bulk create items
	"""

	def render_form_for_serializer(self, serializer):
		if isinstance(serializer, ListSerializer):
			return mark_safe("<p>Form rendering is not available when creating more than one item at a time</p>")
		else:
			return super().render_form_for_serializer(serializer)


class ModelViewSet(XLSXFileMixin, viewsets.ModelViewSet):
	"""
	An extension of the model view set, which accepts a json list of objects
	to create multiple instances at once.
	Also allows XLSX retrieval
	"""

	def create(self, request, *args, **kwargs):
		many = isinstance(request.data, list)
		serializer = self.get_serializer(data=request.data, many=many)
		serializer.is_valid(raise_exception=True)
		self.perform_create(serializer)
		headers = self.get_success_headers(serializer.data)
		return Response(serializer.data, headers=headers)

	def get_renderers(self):
		# we need to disable the HTML form renderer when using Serializer with many=True
		new_renderers = []
		for renderer in self.renderer_classes:
			if isinstance(renderer(), BrowsableAPIRenderer):
				new_renderers.append(SingleInstanceHTMLFormBrowsableAPIRenderer())
			else:
				new_renderers.append(renderer())
		return new_renderers

	def get_filename(self, *args, **kwargs):
		return f"{self.filename}-{export_format_datetime()}.xlsx"


class UserViewSet(ModelViewSet):
	filename = "users"
	queryset = User.objects.all()
	serializer_class = UserSerializer
	filterset_fields = {
		"id": ["exact", "in"],
		"type": ["exact", "in"],
		"domain": ["exact", "in", "isempty"],
		"username": ["iexact", "in"],
		"first_name": ["iexact", "icontains"],
		"last_name": ["iexact", "icontains"],
		"email": ["iexact", "icontains"],
		"badge_number": ["iexact", "isempty"],
		"is_active": ["exact"],
		"is_staff": ["exact"],
		"is_facility_manager": ["exact"],
		"is_superuser": ["exact"],
		"is_service_personnel": ["exact"],
		"is_technician": ["exact"],
		"training_required": ["exact"],
		"date_joined": ["month", "year", "day", "gte", "gt", "lte", "lt"],
		"last_login": ["month", "year", "day", "gte", "gt", "lte", "lt", "isnull"],
		"access_expiration": ["month", "year", "day", "gte", "gt", "lte", "lt", "isnull"],
		"physical_access_levels": ["exact"],
	}


class ProjectDisciplineViewSet(ModelViewSet):
	filename = "project_disciplines"
	queryset = ProjectDiscipline.objects.all()
	serializer_class = ProjectDisciplineSerializer
	filterset_fields = {"id": ["exact", "in"], "name": ["iexact"], "display_order": ["exact"]}


class ProjectViewSet(ModelViewSet):
	filename = "projects"
	queryset = Project.objects.all()
	serializer_class = ProjectSerializer
	filterset_fields = {
		"id": ["exact", "in"],
		"name": ["iexact"],
		"application_identifier": ["exact"],
		"active": ["exact"],
		"account_id": ["exact", "in"],
	}


class AccountTypeViewSet(ModelViewSet):
	filename = "account_types"
	queryset = AccountType.objects.all()
	serializer_class = AccountTypeSerializer
	filterset_fields = {"id": ["exact", "in"], "name": ["exact", "iexact"], "display_order": ["exact"]}


class AccountViewSet(ModelViewSet):
	filename = "accounts"
	queryset = Account.objects.all()
	serializer_class = AccountSerializer
	filterset_fields = {"id": ["exact", "in"], "name": ["exact", "iexact"], "active": ["exact"]}


class ToolViewSet(ModelViewSet):
	filename = "tools"
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


class QualificationViewSet(ModelViewSet):
	filename = "qualifications"
	queryset = Qualification.objects.all()
	serializer_class = QualificationSerializer
	filterset_fields = {
		"id": ["exact", "in"],
		"user": ["exact", "in"],
		"tool": ["exact", "in"],
		"qualified_on": ["exact", "month", "year", "day", "gte", "gt", "lte", "lt"],
	}


class AreaViewSet(ModelViewSet):
	filename = "areas"
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


class ResourceViewSet(ModelViewSet):
	filename = "resources"
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


class ReservationViewSet(ModelViewSet):
	filename = "reservations"
	queryset = Reservation.objects.all()
	serializer_class = ReservationSerializer
	filterset_fields = {
		"id": ["exact", "in"],
		"start": ["month", "year", "day", "gte", "gt", "lte", "lt"],
		"end": ["month", "year", "day", "gte", "gt", "lte", "lt", "isnull"],
		"project_id": ["exact", "in"],
		"user_id": ["exact", "in"],
		"creator_id": ["exact", "in"],
		"tool_id": ["exact", "in", "isnull"],
		"area_id": ["exact", "in", "isnull"],
		"cancelled": ["exact"],
		"missed": ["exact"],
		"validated": ["exact"],
		"question_data": ["isempty"],
	}


class UsageEventViewSet(ModelViewSet):
	filename = "usage_events"
	queryset = UsageEvent.objects.all()
	serializer_class = UsageEventSerializer
	filterset_fields = {
		"id": ["exact", "in"],
		"start": ["month", "year", "day", "gte", "gt", "lte", "lt"],
		"end": ["month", "year", "day", "gte", "gt", "lte", "lt", "isnull"],
		"project_id": ["exact", "in"],
		"user_id": ["exact", "in"],
		"operator_id": ["exact", "in"],
		"tool_id": ["exact", "in"],
		"validated": ["exact"],
	}


class AreaAccessRecordViewSet(ModelViewSet):
	filename = "area_access_records"
	queryset = AreaAccessRecord.objects.all().order_by("-start")
	serializer_class = AreaAccessRecordSerializer
	filterset_fields = {
		"id": ["exact", "in"],
		"start": ["month", "year", "day", "gte", "gt", "lte", "lt"],
		"end": ["month", "year", "day", "gte", "gt", "lte", "lt", "isnull"],
		"project_id": ["exact", "in"],
		"customer_id": ["exact", "in"],
		"area_id": ["exact", "in"],
		"staff_charge_id": ["exact", "isnull", "in"],
		"validated": ["exact"],
	}


class TaskViewSet(ModelViewSet):
	filename = "tasks"
	queryset = Task.objects.all()
	serializer_class = TaskSerializer
	filterset_fields = {
		"id": ["exact", "in"],
		"urgency": ["exact", "gte", "gt", "lte", "lt"],
		"tool_id": ["exact", "in"],
		"force_shutdown": ["exact"],
		"safety_hazard": ["exact"],
		"creator_id": ["exact", "in"],
		"creation_time": ["month", "year", "day", "gte", "gt", "lte", "lt"],
		"estimated_resolution_time": ["month", "year", "day", "gte", "gt", "lte", "lt"],
		"problem_category": ["exact", "in"],
		"cancelled": ["exact"],
		"resolved": ["exact"],
		"resolution_time": ["month", "year", "day", "gte", "gt", "lte", "lt"],
		"resolver_id": ["exact", "in"],
		"resolution_category": ["exact", "in"],
	}


class ScheduledOutageViewSet(ModelViewSet):
	filename = "outages"
	queryset = ScheduledOutage.objects.all()
	serializer_class = ScheduledOutageSerializer
	filterset_fields = {
		"id": ["exact", "in"],
		"start": ["month", "year", "day", "gte", "gt", "lte", "lt"],
		"end": ["month", "year", "day", "gte", "gt", "lte", "lt", "isnull"],
		"creator_id": ["exact", "in"],
		"category": ["exact", "in"],
		"tool_id": ["exact", "in", "isnull"],
		"area_id": ["exact", "in", "isnull"],
		"resource_id": ["exact", "in", "isnull"],
	}


class StaffChargeViewSet(ModelViewSet):
	filename = "staff_charges"
	queryset = StaffCharge.objects.all()
	serializer_class = StaffChargeSerializer
	filterset_fields = {
		"id": ["exact", "in"],
		"staff_member_id": ["exact", "in"],
		"customer_id": ["exact", "in"],
		"project_id": ["exact", "in"],
		"start": ["month", "year", "day", "gte", "gt", "lte", "lt"],
		"end": ["month", "year", "day", "gte", "gt", "lte", "lt", "isnull"],
		"validated": ["exact"],
		"note": ["contains"],
	}


class TrainingSessionViewSet(ModelViewSet):
	filename = "training_sessions"
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
		"date": ["month", "year", "day", "gte", "gt", "lte", "lt"],
		"qualified": ["exact"],
		"validated": ["exact"],
	}


class ConsumableCategoryViewSet(ModelViewSet):
	filename = "consumable_categories"
	queryset = ConsumableCategory.objects.all()
	serializer_class = ConsumableCategorySerializer
	filterset_fields = {"id": ["exact", "in"], "name": ["iexact"]}


class ConsumableViewSet(ModelViewSet):
	filename = "consumables"
	queryset = Consumable.objects.all()
	serializer_class = ConsumableSerializer
	filterset_fields = {
		"id": ["exact", "in"],
		"category_id": ["exact", "in"],
		"quantity": ["exact", "gte", "lte", "gt", "lt"],
		"reminder_threshold": ["exact", "gte", "lte", "gt", "lt"],
		"visible": ["exact"],
		"reusable": ["exact"],
		"reminder_threshold_reached": ["exact"],
	}


class ConsumableWithdrawViewSet(ModelViewSet):
	filename = "consumable_withdrawals"
	queryset = ConsumableWithdraw.objects.all()
	serializer_class = ConsumableWithdrawSerializer
	filterset_fields = {
		"id": ["exact", "in"],
		"customer_id": ["exact", "in"],
		"merchant_id": ["exact", "in"],
		"consumable_id": ["exact", "in"],
		"project_id": ["exact", "in"],
		"quantity": ["exact", "gte", "lte", "gt", "lt"],
		"date": ["month", "year", "day", "gte", "gt", "lte", "lt"],
		"validated": ["exact"],
	}


class ContentTypeViewSet(XLSXFileMixin, viewsets.ReadOnlyModelViewSet):
	filename = "content_types"
	queryset = ContentType.objects.all()
	serializer_class = ContentTypeSerializer
	filterset_fields = {
		"app_label": ["exact", "in"],
		"model": ["exact", "in"],
	}

	def get_filename(self, *args, **kwargs):
		return f"{self.filename}-{export_format_datetime()}.xlsx"


class GroupViewSet(ModelViewSet):
	filename = "groups"
	queryset = Group.objects.all()
	serializer_class = GroupSerializer
	filterset_fields = {
		"name": ["exact", "in"],
		"permissions": ["exact"],
	}


# Should not be able to edit permissions
class PermissionViewSet(XLSXFileMixin, viewsets.ReadOnlyModelViewSet):
	filename = "permissions"
	queryset = Permission.objects.all()
	serializer_class = PermissionSerializer
	filterset_fields = {
		"name": ["exact", "in"],
		"codename": ["exact", "in"],
		"content_type_id": ["exact", "in"],
	}

	def get_filename(self, *args, **kwargs):
		return f"{self.filename}-{export_format_datetime()}.xlsx"


class BillingViewSet(XLSXFileMixin, viewsets.GenericViewSet):
	serializer_class = BillableItemSerializer

	def list(self, request, *args, **kwargs):
		billing_form = BillingFilterForm(self.request.GET)
		if not billing_form.is_valid():
			return Response(status=status.HTTP_400_BAD_REQUEST, data=billing_form.errors)
		queryset = self.get_queryset()
		serializer = self.serializer_class(queryset, many=True)
		return Response(serializer.data)

	def check_permissions(self, request):
		if not request or not request.user.has_perm("NEMO.use_billing_api"):
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
