from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils.safestring import mark_safe
from drf_excel.mixins import XLSXFileMixin
from rest_framework import status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.renderers import BrowsableAPIRenderer
from rest_framework.response import Response
from rest_framework.serializers import ListSerializer

from NEMO.models import (
    Account,
    AccountType,
    Area,
    AreaAccessRecord,
    Configuration,
    ConfigurationOption,
    Consumable,
    ConsumableCategory,
    ConsumableWithdraw,
    Interlock,
    InterlockCard,
    InterlockCardCategory,
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
from NEMO.rest_pagination import NEMOPageNumberPagination
from NEMO.serializers import (
    AccountSerializer,
    AccountTypeSerializer,
    AreaAccessRecordSerializer,
    AreaSerializer,
    BillableItemSerializer,
    ConfigurationOptionSerializer,
    ConfigurationSerializer,
    ConsumableCategorySerializer,
    ConsumableSerializer,
    ConsumableWithdrawSerializer,
    ContentTypeSerializer,
    GroupSerializer,
    InterlockCardCategorySerializer,
    InterlockCardSerializer,
    InterlockSerializer,
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
    ToolStatusSerializer,
    TrainingSessionSerializer,
    UsageEventSerializer,
    UserSerializer,
)
from NEMO.typing import QuerySetType
from NEMO.utilities import export_format_datetime
from NEMO.views.api_billing import (
    BillingFilterForm,
    get_billing_charges,
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

    # Bypass pagination when exporting into any format that's not the browsable API
    def paginate_queryset(self, queryset):
        page_size_override = self.request and self.request.GET.get(NEMOPageNumberPagination.page_size_query_param, None)
        renderer = (
            self.request.accepted_renderer if self.request and hasattr(self.request, "accepted_renderer") else None
        )
        if page_size_override is not None or not renderer or isinstance(renderer, BrowsableAPIRenderer):
            return super().paginate_queryset(queryset)
        return None

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        many = isinstance(request.data, list)
        serializer = self.get_serializer(data=request.data, many=many)
        serializer.is_valid(raise_exception=True)
        try:
            self.perform_create(serializer)
        except Exception as e:
            raise ValidationError({"error": str(e)})
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
        "username": ["exact", "iexact", "in"],
        "first_name": ["exact", "iexact", "icontains"],
        "last_name": ["exact", "iexact", "icontains"],
        "email": ["exact", "iexact", "icontains"],
        "badge_number": ["exact", "iexact", "isempty"],
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
    filterset_fields = {"id": ["exact", "in"], "name": ["exact", "iexact"], "display_order": ["exact"]}


class ProjectViewSet(ModelViewSet):
    filename = "projects"
    queryset = Project.objects.all()
    serializer_class = ProjectSerializer
    filterset_fields = {
        "id": ["exact", "in"],
        "name": ["exact", "iexact"],
        "application_identifier": ["exact", "iexact"],
        "active": ["exact"],
        "account_id": ["exact", "in"],
        "account": ["exact", "in"],
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
        "name": ["exact", "iexact"],
        "visible": ["exact"],
        "_category": ["exact", "iexact"],
        "_operational": ["exact"],
        "_location": ["exact", "iexact"],
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
        "name": ["exact", "iexact"],
        "parent_area": ["exact", "in"],
        "category": ["exact", "iexact"],
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
        "name": ["exact", "iexact"],
        "available": ["exact"],
        "fully_dependent_tools": ["exact"],
        "partially_dependent_tools": ["exact"],
        "dependent_areas": ["exact"],
    }


class ConfigurationViewSet(ModelViewSet):
    filename = "configurations"
    queryset = Configuration.objects.all()
    serializer_class = ConfigurationSerializer
    filterset_fields = {
        "id": ["exact", "in"],
        "name": ["exact", "iexact", "in"],
        "tool_id": ["exact", "in", "isnull"],
        "tool": ["exact", "in", "isnull"],
        "advance_notice_limit": ["exact", "in", "gte", "gt", "lte", "lt"],
        "display_order": ["exact", "in", "gte", "gt", "lte", "lt"],
        "maintainers": ["exact", "isnull"],
        "qualified_users_are_maintainers": ["exact"],
        "exclude_from_configuration_agenda": ["exact"],
        "enabled": ["exact"],
    }


class ConfigurationOptionViewSet(ModelViewSet):
    filename = "reservation_configuration_options"
    queryset = ConfigurationOption.objects.all()
    serializer_class = ConfigurationOptionSerializer
    filterset_fields = {
        "id": ["exact", "in"],
        "name": ["exact", "iexact", "in"],
        "reservation_id": ["exact", "in", "isnull"],
        "reservation": ["exact", "in", "isnull"],
        "configuration_id": ["exact", "in", "isnull"],
        "configuration": ["exact", "in", "isnull"],
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
        "project": ["exact", "in"],
        "user_id": ["exact", "in"],
        "user": ["exact", "in"],
        "creator_id": ["exact", "in"],
        "creator": ["exact", "in"],
        "tool_id": ["exact", "in", "isnull"],
        "tool": ["exact", "in", "isnull"],
        "area_id": ["exact", "in", "isnull"],
        "area": ["exact", "in", "isnull"],
        "cancelled": ["exact"],
        "missed": ["exact"],
        "validated": ["exact"],
        "validated_by": ["exact", "in", "isnull"],
        "question_data": ["isnull", "isempty"],
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
        "project": ["exact", "in"],
        "user_id": ["exact", "in"],
        "user": ["exact", "in"],
        "operator_id": ["exact", "in"],
        "operator": ["exact", "in"],
        "tool_id": ["exact", "in"],
        "tool": ["exact", "in"],
        "validated": ["exact"],
        "validated_by": ["exact", "in", "isnull"],
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
        "project": ["exact", "in"],
        "customer_id": ["exact", "in"],
        "customer": ["exact", "in"],
        "area_id": ["exact", "in"],
        "area": ["exact", "in"],
        "staff_charge_id": ["exact", "isnull", "in"],
        "staff_charge": ["exact", "isnull", "in"],
        "validated": ["exact"],
        "validated_by": ["exact", "in", "isnull"],
    }


class TaskViewSet(ModelViewSet):
    filename = "tasks"
    queryset = Task.objects.all()
    serializer_class = TaskSerializer
    filterset_fields = {
        "id": ["exact", "in"],
        "urgency": ["exact", "gte", "gt", "lte", "lt"],
        "tool_id": ["exact", "in"],
        "tool": ["exact", "in"],
        "force_shutdown": ["exact"],
        "safety_hazard": ["exact"],
        "creator_id": ["exact", "in"],
        "creator": ["exact", "in"],
        "creation_time": ["month", "year", "day", "gte", "gt", "lte", "lt"],
        "estimated_resolution_time": ["month", "year", "day", "gte", "gt", "lte", "lt"],
        "problem_category": ["exact", "in"],
        "cancelled": ["exact"],
        "resolved": ["exact"],
        "resolution_time": ["month", "year", "day", "gte", "gt", "lte", "lt"],
        "resolver_id": ["exact", "in"],
        "resolver": ["exact", "in"],
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
        "creator": ["exact", "in"],
        "category": ["exact", "in"],
        "tool_id": ["exact", "in", "isnull"],
        "tool": ["exact", "in", "isnull"],
        "area_id": ["exact", "in", "isnull"],
        "area": ["exact", "in", "isnull"],
        "resource_id": ["exact", "in", "isnull"],
        "resource": ["exact", "in", "isnull"],
    }


class StaffChargeViewSet(ModelViewSet):
    filename = "staff_charges"
    queryset = StaffCharge.objects.all()
    serializer_class = StaffChargeSerializer
    filterset_fields = {
        "id": ["exact", "in"],
        "staff_member_id": ["exact", "in"],
        "staff_member": ["exact", "in"],
        "customer_id": ["exact", "in"],
        "customer": ["exact", "in"],
        "project_id": ["exact", "in"],
        "project": ["exact", "in"],
        "start": ["month", "year", "day", "gte", "gt", "lte", "lt"],
        "end": ["month", "year", "day", "gte", "gt", "lte", "lt", "isnull"],
        "validated": ["exact"],
        "validated_by": ["exact", "in", "isnull"],
        "note": ["contains"],
    }


class TrainingSessionViewSet(ModelViewSet):
    filename = "training_sessions"
    queryset = TrainingSession.objects.all()
    serializer_class = TrainingSessionSerializer
    filterset_fields = {
        "id": ["exact", "in"],
        "trainer_id": ["exact", "in"],
        "trainer": ["exact", "in"],
        "trainee_id": ["exact", "in"],
        "trainee": ["exact", "in"],
        "tool_id": ["exact", "in"],
        "tool": ["exact", "in"],
        "project_id": ["exact", "in"],
        "project": ["exact", "in"],
        "duration": ["exact", "gte", "lte", "gt", "lt"],
        "type": ["exact", "in"],
        "date": ["month", "year", "day", "gte", "gt", "lte", "lt"],
        "qualified": ["exact"],
        "validated": ["exact"],
        "validated_by": ["exact", "in", "isnull"],
    }


class ConsumableCategoryViewSet(ModelViewSet):
    filename = "consumable_categories"
    queryset = ConsumableCategory.objects.all()
    serializer_class = ConsumableCategorySerializer
    filterset_fields = {"id": ["exact", "in"], "name": ["exact", "iexact"]}


class ConsumableViewSet(ModelViewSet):
    filename = "consumables"
    queryset = Consumable.objects.all()
    serializer_class = ConsumableSerializer
    filterset_fields = {
        "id": ["exact", "in"],
        "category_id": ["exact", "in"],
        "category": ["exact", "in"],
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
        "customer": ["exact", "in"],
        "merchant_id": ["exact", "in"],
        "merchant": ["exact", "in"],
        "consumable_id": ["exact", "in"],
        "consumable": ["exact", "in"],
        "project_id": ["exact", "in"],
        "project": ["exact", "in"],
        "quantity": ["exact", "gte", "lte", "gt", "lt"],
        "date": ["month", "year", "day", "gte", "gt", "lte", "lt"],
        "validated": ["exact"],
        "validated_by": ["exact", "in", "isnull"],
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


class InterlockCardCategoryViewSet(ModelViewSet):
    filename = "interlock_card_categories"
    queryset = InterlockCardCategory.objects.all()
    serializer_class = InterlockCardCategorySerializer
    filterset_fields = {
        "name": ["exact", "iexact", "in"],
        "key": ["exact", "iexact", "in"],
    }


class InterlockCardViewSet(ModelViewSet):
    filename = "interlock_cards"
    queryset = InterlockCard.objects.all()
    serializer_class = InterlockCardSerializer
    filterset_fields = {
        "name": ["exact", "iexact", "in"],
        "server": ["exact", "iexact", "in"],
        "number": ["exact", "in", "gte", "lte", "gt", "lt"],
        "even_port": ["exact", "in", "gte", "lte", "gt", "lt"],
        "odd_port": ["exact", "in", "gte", "lte", "gt", "lt"],
        "category": ["exact", "in"],
        "enabled": ["exact"],
    }


class InterlockViewSet(ModelViewSet):
    filename = "interlocks"
    queryset = Interlock.objects.all()
    serializer_class = InterlockSerializer
    filterset_fields = {
        "card": ["exact", "in"],
        "channel": ["exact", "in", "gte", "lte", "gt", "lt"],
        "unit_id": ["exact", "in", "gte", "lte", "gt", "lt"],
        "state": ["exact", "in", "gte", "lte", "gt", "lt"],
        "most_recent_reply_time": ["exact", "in", "gte", "lte", "gt", "lt"],
    }


class GroupViewSet(ModelViewSet):
    filename = "groups"
    queryset = Group.objects.all()
    serializer_class = GroupSerializer
    filterset_fields = {
        "name": ["exact", "iexact", "in"],
        "permissions": ["exact"],
    }


# Should not be able to edit permissions
class PermissionViewSet(XLSXFileMixin, viewsets.ReadOnlyModelViewSet):
    filename = "permissions"
    queryset = Permission.objects.all()
    serializer_class = PermissionSerializer
    filterset_fields = {
        "name": ["exact", "iexact", "in"],
        "codename": ["exact", "iexact", "in"],
        "content_type_id": ["exact", "in"],
        "content_type": ["exact", "in"],
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
        return get_billing_charges(self.request.GET)

    def get_filename(self, *args, **kwargs):
        return f"billing-{export_format_datetime()}.xlsx"


class ToolStatusViewSet(XLSXFileMixin, viewsets.GenericViewSet):
    serializer_class = ToolStatusSerializer

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.serializer_class(queryset, many=True)
        return Response(serializer.data)

    def check_permissions(self, request):
        if not request or not request.user.has_perm("NEMO.view_tool"):
            self.permission_denied(request)

    def get_queryset(self) -> QuerySetType[Tool]:
        tools: QuerySetType[Tool] = Tool.objects.all()
        for tool in tools:
            pbs = tool.problems()
            outages = tool.scheduled_outages()
            partial_outages = tool.scheduled_partial_outages()
            rss_unavailable = tool.unavailable_required_resources()
            partial_rss_unavailable = tool.unavailable_nonrequired_resources()
            tool.problem_descriptions = ", ".join(pb.problem_description for pb in pbs) if pbs else None
            tool.outages = ", ".join(outage.title for outage in outages) if outages else None
            tool.partial_outages = ", ".join(outage.title for outage in partial_outages) if partial_outages else None
            tool.required_resources_unavailable = (
                ", ".join(res.name for res in rss_unavailable) if rss_unavailable else None
            )
            tool.optional_resources_unavailable = (
                ", ".join(res.name for res in partial_rss_unavailable) if partial_rss_unavailable else None
            )
        return tools

    def get_filename(self, *args, **kwargs):
        return f"tool_status-{export_format_datetime()}.xlsx"
