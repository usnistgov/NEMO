from copy import deepcopy

from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core import validators
from django.utils.translation import gettext_lazy as _
from rest_flex_fields.serializers import FlexFieldsSerializerMixin
from rest_framework import serializers
from rest_framework.fields import (
    BooleanField,
    CharField,
    ChoiceField,
    DateTimeField,
    DecimalField,
    IntegerField,
    JSONField,
)
from rest_framework.relations import PrimaryKeyRelatedField
from rest_framework.utils import model_meta

from NEMO.constants import CHAR_FIELD_LARGE_LENGTH, CHAR_FIELD_MEDIUM_LENGTH
from NEMO.fields import DEFAULT_SEPARATOR, MultiEmailField
from NEMO.models import (
    Account,
    AccountType,
    AdjustmentRequest,
    Alert,
    AlertCategory,
    Area,
    AreaAccessRecord,
    BuddyRequest,
    Comment,
    Configuration,
    ConfigurationOption,
    Consumable,
    ConsumableCategory,
    ConsumableWithdraw,
    Customization,
    Interlock,
    InterlockCard,
    InterlockCardCategory,
    PhysicalAccessLevel,
    Project,
    ProjectDiscipline,
    ProjectType,
    Qualification,
    RecurringConsumableCharge,
    Reservation,
    ReservationQuestions,
    Resource,
    ScheduledOutage,
    StaffAssistanceRequest,
    StaffCharge,
    Task,
    TaskHistory,
    TemporaryPhysicalAccessRequest,
    Tool,
    ToolCredentials,
    ToolUsageCounter,
    ToolUsageQuestions,
    TrainingSession,
    UsageEvent,
    User,
    UserDocuments,
    UserPreferences,
)


class MultiEmailSerializerField(serializers.CharField):
    def __init__(self, separator=DEFAULT_SEPARATOR, **kwargs):
        self.email_validator = validators.EmailValidator(
            message=_("Enter a valid email address or a list separated by {}").format(separator)
        )
        self.separator = separator
        kwargs.setdefault("max_length", 2000)
        super().__init__(**kwargs)

    def to_internal_value(self, data):
        emails = data.split(self.separator)
        for email in emails:
            email = email.strip()
            self.email_validator(email)
        return emails

    def to_representation(self, value):
        return ",".join(value)


# Overriding validate to call model full_clean
class ModelSerializer(serializers.ModelSerializer):
    serializer_field_mapping = serializers.ModelSerializer.serializer_field_mapping.copy()
    serializer_field_mapping[MultiEmailField] = MultiEmailSerializerField

    def validate(self, attrs):
        attributes_data = dict(attrs)
        ModelClass = self.Meta.model
        instance = deepcopy(self.instance) if self.instance else ModelClass()
        # Remove many-to-many relationships from attributes_data, so we can properly validate.
        info = model_meta.get_field_info(ModelClass)
        for field_name, relation_info in info.relations.items():
            if relation_info.to_many and (field_name in attributes_data):
                attributes_data.pop(field_name)
        for attr, value in attributes_data.items():
            setattr(instance, attr, value)
        exclude = self.get_validation_exclusions(instance, attributes_data)
        self.full_clean(instance, exclude)
        return attrs

    def get_validation_exclusions(self, instance, attributes_data):
        exclude = []
        # Build up a list of fields that should be excluded from model field
        # validation and unique checks.
        for f in instance._meta.fields:
            field = f.name
            meta_fields = getattr(self.Meta, "fields", None)
            meta_exclude = getattr(self.Meta, "exclude", None)

            # Exclude fields that aren't on the serializer.
            if field not in self.fields:
                exclude.append(f.name)

            # Don't perform model validation on fields that were defined
            # manually on the form and excluded via the Serializer's Meta
            # class.
            elif meta_fields and meta_fields != "__all__" and field not in meta_fields:
                exclude.append(f.name)
            elif meta_exclude and field in meta_exclude:
                exclude.append(f.name)

            # Exclude empty fields that are not required by the serializer, if
            # the underlying model field is required. This keeps the model field
            # from raising a required error. Note: don't exclude the field from
            # validation if the model field allows blanks. If it does, the blank
            # value may be included in a unique check, so cannot be excluded
            # from validation.
            else:
                form_field = self.fields[field]
                field_value = attributes_data.get(field)
                if not f.blank and not form_field.required and field_value in list(validators.EMPTY_VALUES):
                    exclude.append(f.name)
        return exclude

    def full_clean(self, instance, exclude=None, validate_unique=True):
        instance.full_clean(exclude, validate_unique)


class AlertCategorySerializer(ModelSerializer):
    class Meta:
        model = AlertCategory
        fields = "__all__"


class AlertSerializer(FlexFieldsSerializerMixin, ModelSerializer):
    class Meta:
        model = Alert
        fields = "__all__"
        expandable_fields = {
            "creator": "NEMO.serializers.UserSerializer",
            "user": "NEMO.serializers.UserSerializer",
        }


class UserSerializer(FlexFieldsSerializerMixin, ModelSerializer):
    user_documents = serializers.PrimaryKeyRelatedField(many=True, read_only=True)

    class Meta:
        model = User
        exclude = ["preferences"]
        expandable_fields = {
            "projects": ("NEMO.serializers.ProjectSerializer", {"many": True}),
            "managed_projects": ("NEMO.serializers.ProjectSerializer", {"many": True}),
            "groups": ("NEMO.serializers.GroupSerializer", {"many": True}),
            "user_documents": ("NEMO.serializers.UserDocumentSerializer", {"many": True}),
            "user_permissions": ("NEMO.serializers.PermissionSerializer", {"many": True}),
        }

    def to_internal_value(self, data):
        # Unique and nullable field conflict if passed the empty string so set
        # it to None instead. Very specific case for nullable unique CharField
        if data.get("badge_number", None) == "":
            data = data.copy()
            data["badge_number"] = None
        return super().to_internal_value(data)


class ProjectDisciplineSerializer(ModelSerializer):
    class Meta:
        model = ProjectDiscipline
        fields = "__all__"


class UserDocumentSerializer(FlexFieldsSerializerMixin, ModelSerializer):
    user = PrimaryKeyRelatedField(queryset=User.objects.all())

    class Meta:
        model = UserDocuments
        fields = "__all__"
        expandable_fields = {
            "user": "NEMO.serializers.UserSerializer",
        }


class UserPreferenceSerializer(FlexFieldsSerializerMixin, ModelSerializer):
    user = PrimaryKeyRelatedField(queryset=User.objects.all(), required=False)

    class Meta:
        model = UserPreferences
        fields = "__all__"
        expandable_fields = {
            "user": "NEMO.serializers.UserSerializer",
        }


class ProjectTypeSerializer(FlexFieldsSerializerMixin, ModelSerializer):
    class Meta:
        model = ProjectType
        fields = "__all__"


class ProjectSerializer(FlexFieldsSerializerMixin, ModelSerializer):
    principal_investigators = PrimaryKeyRelatedField(
        source="manager_set", many=True, queryset=User.objects.all(), allow_null=True, required=False
    )
    users = PrimaryKeyRelatedField(
        source="user_set", many=True, queryset=User.objects.all(), allow_null=True, required=False
    )

    class Meta:
        model = Project
        fields = "__all__"
        expandable_fields = {
            "account": "NEMO.serializers.AccountSerializer",
            "only_allow_tools": ("NEMO.serializers.ToolSerializer", {"many": True}),
            "principal_investigators": ("NEMO.serializers.UserSerializer", {"source": "manager_set", "many": True}),
            "users": ("NEMO.serializers.UserSerializer", {"source": "user_set", "many": True}),
            "project_types": ("NEMO.serializers.ProjectTypeSerializer", {"many": True}),
        }


class AccountTypeSerializer(FlexFieldsSerializerMixin, ModelSerializer):
    class Meta:
        model = AccountType
        fields = "__all__"


class AccountSerializer(FlexFieldsSerializerMixin, ModelSerializer):
    class Meta:
        model = Account
        fields = "__all__"
        expandable_fields = {
            "type": "NEMO.serializers.AccountTypeSerializer",
        }


class QualificationSerializer(FlexFieldsSerializerMixin, ModelSerializer):
    class Meta:
        model = Qualification
        fields = "__all__"
        expandable_fields = {
            "user": "NEMO.serializers.UserSerializer",
            "tool": "NEMO.serializers.ToolSerializer",
        }


class ToolSerializer(FlexFieldsSerializerMixin, ModelSerializer):
    class Meta:
        model = Tool
        fields = "__all__"
        expandable_fields = {
            "parent_tool": "NEMO.serializers.ToolSerializer",
            "_primary_owner": "NEMO.serializers.UserSerializer",
            "_backup_owners": ("NEMO.serializers.UserSerializer", {"many": True}),
            "_superusers": ("NEMO.serializers.UserSerializer", {"many": True}),
            "_requires_area_access": "NEMO.serializers.AreaSerializer",
            "project": "NEMO.serializers.ProjectSerializer",
        }


class AreaSerializer(FlexFieldsSerializerMixin, ModelSerializer):
    class Meta:
        model = Area
        fields = "__all__"
        expandable_fields = {"parent_area": "NEMO.serializers.AreaSerializer"}


class ConfigurationOptionSerializer(FlexFieldsSerializerMixin, ModelSerializer):
    class Meta:
        model = ConfigurationOption
        fields = "__all__"
        expandable_fields = {
            "reservation": "NEMO.serializers.ReservationSerializer",
            "configuration": "NEMO.serializers.ConfigurationSerializer",
        }


class ConfigurationSerializer(FlexFieldsSerializerMixin, ModelSerializer):
    class Meta:
        model = Configuration
        fields = "__all__"
        expandable_fields = {
            "tool": "NEMO.serializers.ToolSerializer",
        }


class ReservationSerializer(FlexFieldsSerializerMixin, ModelSerializer):
    question_data = JSONField(source="question_data_json", allow_null=True, required=False)
    configuration_options = ConfigurationOptionSerializer(source="configurationoption_set", many=True, read_only=True)

    class Meta:
        model = Reservation
        fields = "__all__"
        expandable_fields = {
            "user": "NEMO.serializers.UserSerializer",
            "creator": "NEMO.serializers.UserSerializer",
            "cancelled_by": "NEMO.serializers.UserSerializer",
            "tool": "NEMO.serializers.ToolSerializer",
            "area": "NEMO.serializers.AreaSerializer",
            "project": "NEMO.serializers.ProjectSerializer",
            "descendant": "NEMO.serializers.ReservationSerializer",
            "configuration_options": ("NEMO.serializers.ConfigurationOptionSerializer", {"many": True}),
            "validated_by": "NEMO.serializers.UserSerializer",
            "waived_by": "NEMO.serializers.UserSerializer",
        }


class ReservationQuestionsSerializer(FlexFieldsSerializerMixin, ModelSerializer):
    class Meta:
        model = ReservationQuestions
        fields = "__all__"
        expandable_fields = {
            "only_for_tools": ("NEMO.serializers.ToolSerializer", {"many": True}),
            "only_for_areas": ("NEMO.serializers.AreaSerializer", {"many": True}),
            "only_for_projects": ("NEMO.serializers.ProjectSerializer", {"many": True}),
        }


class UsageEventSerializer(FlexFieldsSerializerMixin, ModelSerializer):
    class Meta:
        model = UsageEvent
        fields = "__all__"
        expandable_fields = {
            "user": "NEMO.serializers.UserSerializer",
            "operator": "NEMO.serializers.UserSerializer",
            "tool": "NEMO.serializers.ToolSerializer",
            "project": "NEMO.serializers.ProjectSerializer",
            "validated_by": "NEMO.serializers.UserSerializer",
            "waived_by": "NEMO.serializers.UserSerializer",
        }


class AreaAccessRecordSerializer(FlexFieldsSerializerMixin, ModelSerializer):
    class Meta:
        model = AreaAccessRecord
        fields = "__all__"
        expandable_fields = {
            "customer": "NEMO.serializers.UserSerializer",
            "area": "NEMO.serializers.AreaSerializer",
            "project": "NEMO.serializers.ProjectSerializer",
            "staff_charge": "NEMO.serializers.StaffChargeSerializer",
            "validated_by": "NEMO.serializers.UserSerializer",
            "waived_by": "NEMO.serializers.UserSerializer",
        }


class TaskHistorySerializer(FlexFieldsSerializerMixin, ModelSerializer):
    class Meta:
        model = TaskHistory
        fields = "__all__"
        expandable_fields = {"user": "NEMO.serializers.UserSerializer", "task": "NEMO.serializers.TaskSerializer"}


class TaskSerializer(FlexFieldsSerializerMixin, ModelSerializer):
    history = TaskHistorySerializer(many=True, read_only=True)

    class Meta:
        model = Task
        fields = "__all__"
        expandable_fields = {
            "tool": "NEMO.serializers.ToolSerializer",
            "creator": "NEMO.serializers.UserSerializer",
            "last_updated_by": "NEMO.serializers.UserSerializer",
            "resolver": "NEMO.serializers.UserSerializer",
        }


class ScheduledOutageSerializer(FlexFieldsSerializerMixin, ModelSerializer):
    class Meta:
        model = ScheduledOutage
        fields = "__all__"
        expandable_fields = {
            "creator": "NEMO.serializers.UserSerializer",
            "tool": "NEMO.serializers.ToolSerializer",
            "area": "NEMO.serializers.AreaSerializer",
            "resource": "NEMO.serializers.ResourceSerializer",
        }


class TrainingSessionSerializer(FlexFieldsSerializerMixin, ModelSerializer):
    class Meta:
        model = TrainingSession
        fields = "__all__"
        expandable_fields = {
            "trainer": "NEMO.serializers.UserSerializer",
            "trainee": "NEMO.serializers.UserSerializer",
            "tool": "NEMO.serializers.ToolSerializer",
            "project": "NEMO.serializers.ProjectSerializer",
            "validated_by": "NEMO.serializers.UserSerializer",
            "waived_by": "NEMO.serializers.UserSerializer",
        }


class StaffChargeSerializer(FlexFieldsSerializerMixin, ModelSerializer):
    class Meta:
        model = StaffCharge
        fields = "__all__"
        expandable_fields = {
            "customer": "NEMO.serializers.UserSerializer",
            "staff_member": "NEMO.serializers.UserSerializer",
            "project": "NEMO.serializers.ProjectSerializer",
            "validated_by": "NEMO.serializers.UserSerializer",
            "waived_by": "NEMO.serializers.UserSerializer",
        }


class ResourceSerializer(FlexFieldsSerializerMixin, ModelSerializer):
    class Meta:
        model = Resource
        fields = "__all__"
        expandable_fields = {
            "fully_dependent_tools": ("NEMO.serializers.ToolSerializer", {"many": True}),
            "partially_dependent_tools": ("NEMO.serializers.ToolSerializer", {"many": True}),
            "dependent_areas": ("NEMO.serializers.AreaSerializer", {"many": True}),
        }


class ConsumableCategorySerializer(FlexFieldsSerializerMixin, ModelSerializer):
    class Meta:
        model = ConsumableCategory
        fields = "__all__"


class ConsumableSerializer(FlexFieldsSerializerMixin, ModelSerializer):
    class Meta:
        model = Consumable
        fields = "__all__"
        expandable_fields = {
            "category": "NEMO.serializers.ConsumableCategorySerializer",
        }


class ConsumableWithdrawSerializer(FlexFieldsSerializerMixin, ModelSerializer):
    class Meta:
        model = ConsumableWithdraw
        fields = "__all__"
        expandable_fields = {
            "customer": "NEMO.serializers.UserSerializer",
            "merchant": "NEMO.serializers.UserSerializer",
            "consumable": "NEMO.serializers.ConsumableSerializer",
            "project": "NEMO.serializers.ProjectSerializer",
            "validated_by": "NEMO.serializers.UserSerializer",
            "waived_by": "NEMO.serializers.UserSerializer",
        }


class ContentTypeSerializer(ModelSerializer):
    class Meta:
        model = ContentType
        fields = "__all__"


class CustomizationSerializer(ModelSerializer):
    class Meta:
        model = Customization
        fields = "__all__"


class InterlockCardCategorySerializer(ModelSerializer):
    class Meta:
        model = InterlockCardCategory
        fields = "__all__"


class InterlockCardSerializer(FlexFieldsSerializerMixin, ModelSerializer):
    class Meta:
        model = InterlockCard
        fields = "__all__"
        expandable_fields = {
            "category": "NEMO.serializers.InterlockCardCategorySerializer",
        }


class InterlockSerializer(FlexFieldsSerializerMixin, ModelSerializer):
    class Meta:
        model = Interlock
        fields = "__all__"
        expandable_fields = {
            "card": "NEMO.serializers.InterlockCardSerializer",
        }


class RecurringConsumableChargeSerializer(FlexFieldsSerializerMixin, ModelSerializer):
    class Meta:
        model = RecurringConsumableCharge
        fields = "__all__"
        expandable_fields = {
            "customer": "NEMO.serializers.UserSerializer",
            "last_updated_by": "NEMO.serializers.UserSerializer",
            "consumable": "NEMO.serializers.ConsumableSerializer",
            "project": "NEMO.serializers.ProjectSerializer",
        }


class PhysicalAccessLevelSerializer(FlexFieldsSerializerMixin, ModelSerializer):
    class Meta:
        model = PhysicalAccessLevel
        fields = "__all__"
        expandable_fields = {"area": "NEMO.serializers.AreaSerializer"}


class BuddyRequestSerializer(FlexFieldsSerializerMixin, ModelSerializer):
    class Meta:
        model = BuddyRequest
        fields = "__all__"
        expandable_fields = {
            "area": "NEMO.serializers.AreaSerializer",
            "user": "NEMO.serializers.UserSerializer",
        }


class TemporaryPhysicalAccessRequestSerializer(FlexFieldsSerializerMixin, ModelSerializer):
    class Meta:
        model = TemporaryPhysicalAccessRequest
        fields = "__all__"
        expandable_fields = {
            "creator": "NEMO.serializers.UserSerializer",
            "last_updated_by": "NEMO.serializers.UserSerializer",
            "physical_access_level": "NEMO.serializers.PhysicalAccessLevelSerializer",
            "other_users": ("NEMO.serializers.UserSerializer", {"many": True}),
        }


class AdjustmentRequestSerializer(FlexFieldsSerializerMixin, ModelSerializer):
    class Meta:
        model = AdjustmentRequest
        fields = "__all__"
        expandable_fields = {
            "creator": "NEMO.serializers.UserSerializer",
            "last_updated_by": "NEMO.serializers.UserSerializer",
            "reviewer": "NEMO.serializers.UserSerializer",
            "item_type": "NEMO.serializers.ContentTypeSerializer",
            "applied_by": "NEMO.serializers.UserSerializer",
            "new_project": "NEMO.serializers.ProjectSerializer",
        }


class ToolUsageQuestionsSerializer(FlexFieldsSerializerMixin, ModelSerializer):
    class Meta:
        model = ToolUsageQuestions
        fields = "__all__"
        expandable_fields = {
            "tool": "NEMO.serializers.ToolSerializer",
            "only_for_projects": ("NEMO.serializers.ProjectSerializer", {"many": True}),
        }


class ToolUsageCounterSerializer(FlexFieldsSerializerMixin, ModelSerializer):
    class Meta:
        model = ToolUsageCounter
        fields = "__all__"
        expandable_fields = {
            "tool": "NEMO.serializers.ToolSerializer",
            "last_reset_by": "NEMO.serializers.UserSerializer",
        }


class ToolCredentialsSerializer(FlexFieldsSerializerMixin, ModelSerializer):
    class Meta:
        model = ToolCredentials
        fields = "__all__"
        expandable_fields = {
            "tool": "NEMO.serializers.ToolSerializer",
            "authorized_staff": ("NEMO.serializers.UserSerializer", {"many": True}),
        }


class ToolCommentSerializer(FlexFieldsSerializerMixin, ModelSerializer):
    class Meta:
        model = Comment
        fields = "__all__"
        expandable_fields = {
            "tool": "NEMO.serializers.ToolSerializer",
            "author": "NEMO.serializers.UserSerializer",
            "hidden_by": "NEMO.serializers.UserSerializer",
        }


class StaffAssistanceRequestSerializer(FlexFieldsSerializerMixin, ModelSerializer):
    class Meta:
        model = StaffAssistanceRequest
        fields = "__all__"
        expandable_fields = {
            "tool": "NEMO.serializers.ToolSerializer",
            "user": "NEMO.serializers.UserSerializer",
        }


class PermissionSerializer(FlexFieldsSerializerMixin, ModelSerializer):
    users = PrimaryKeyRelatedField(
        source="user_set", many=True, queryset=User.objects.all(), allow_null=True, required=False
    )

    class Meta:
        model = Permission
        fields = "__all__"
        expandable_fields = {
            "content_type": "NEMO.serializers.ContentTypeSerializer",
            "users": ("NEMO.serializers.UserSerializer", {"source": "user_set", "many": True}),
        }


class GroupSerializer(FlexFieldsSerializerMixin, ModelSerializer):
    users = PrimaryKeyRelatedField(
        source="user_set", many=True, queryset=User.objects.all(), allow_null=True, required=False
    )

    class Meta:
        model = Group
        fields = "__all__"
        expandable_fields = {
            "permissions": ("NEMO.serializers.PermissionSerializer", {"many": True}),
            "users": ("NEMO.serializers.UserSerializer", {"source": "user_set", "many": True}),
        }


class BillableItemSerializer(serializers.Serializer):
    type = ChoiceField(
        ["missed_reservation", "tool_usage", "area_access", "consumable", "staff_charge", "training_session"]
    )
    name = CharField(max_length=CHAR_FIELD_MEDIUM_LENGTH, read_only=True)
    item_id = IntegerField(read_only=True)
    details = CharField(max_length=500, read_only=True)
    account = CharField(max_length=CHAR_FIELD_MEDIUM_LENGTH, read_only=True)
    account_id = IntegerField(read_only=True)
    project = CharField(max_length=CHAR_FIELD_MEDIUM_LENGTH, read_only=True)
    project_id = IntegerField(read_only=True)
    application = CharField(max_length=CHAR_FIELD_MEDIUM_LENGTH, read_only=True)
    user = CharField(max_length=CHAR_FIELD_MEDIUM_LENGTH, read_only=True)
    username = CharField(max_length=CHAR_FIELD_MEDIUM_LENGTH, read_only=True)
    user_id = IntegerField(read_only=True)
    start = DateTimeField(read_only=True)
    end = DateTimeField(read_only=True)
    quantity = DecimalField(read_only=True, decimal_places=2, max_digits=8)
    validated = BooleanField(read_only=True)
    validated_by = CharField(read_only=True, source="validated_by.username", allow_null=True)
    waived = BooleanField(read_only=True)
    waived_by = CharField(read_only=True, source="waived_by.username", allow_null=True)
    waived_on = DateTimeField(read_only=True)

    def update(self, instance, validated_data):
        pass

    def create(self, validated_data):
        pass

    class Meta:
        fields = "__all__"


class ToolStatusSerializer(serializers.Serializer):
    id = IntegerField(read_only=True)
    name = CharField(max_length=CHAR_FIELD_MEDIUM_LENGTH, read_only=True)
    category = CharField(max_length=CHAR_FIELD_MEDIUM_LENGTH, read_only=True)
    in_use = BooleanField(read_only=True)
    visible = BooleanField(read_only=True)
    operational = BooleanField(read_only=True)
    problematic = BooleanField(read_only=True)
    problem_descriptions = CharField(default=None, max_length=CHAR_FIELD_LARGE_LENGTH, read_only=True)
    customer_id = IntegerField(default=None, source="get_current_usage_event.user.id", read_only=True)
    customer_name = CharField(
        default=None,
        source="get_current_usage_event.user.get_name",
        max_length=CHAR_FIELD_MEDIUM_LENGTH,
        read_only=True,
    )
    customer_username = CharField(
        default=None,
        source="get_current_usage_event.user.username",
        max_length=CHAR_FIELD_MEDIUM_LENGTH,
        read_only=True,
    )
    operator_id = IntegerField(default=None, source="get_current_usage_event.operator.id", read_only=True)
    operator_name = CharField(
        default=None,
        source="get_current_usage_event.operator.get_name",
        max_length=CHAR_FIELD_MEDIUM_LENGTH,
        read_only=True,
    )
    operator_username = CharField(
        default=None,
        source="get_current_usage_event.operator.username",
        max_length=CHAR_FIELD_MEDIUM_LENGTH,
        read_only=True,
    )
    current_usage_id = IntegerField(default=None, source="get_current_usage_event.id", read_only=True)
    current_usage_start = DateTimeField(default=None, source="get_current_usage_event.start", read_only=True)
    outages = CharField(default=None, max_length=2000, read_only=True)
    partial_outages = CharField(default=None, max_length=2000, read_only=True)
    required_resources_unavailable = CharField(default=None, max_length=2000, read_only=True)
    optional_resources_unavailable = CharField(default=None, max_length=2000, read_only=True)

    def update(self, instance, validated_data):
        pass

    def create(self, validated_data):
        pass

    class Meta:
        fields = "__all__"
