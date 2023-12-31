from copy import deepcopy

from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core import validators
from rest_flex_fields.serializers import FlexFieldsSerializerMixin
from rest_framework import serializers
from rest_framework.fields import CharField, ChoiceField, DateTimeField, DecimalField, IntegerField
from rest_framework.relations import PrimaryKeyRelatedField
from rest_framework.utils import model_meta

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
    Project,
    ProjectDiscipline,
    Qualification,
    Reservation,
    Resource,
    ScheduledOutage,
    StaffCharge,
    Task,
    TaskHistory,
    Tool,
    TrainingSession,
    UsageEvent,
    User,
)


# Overriding validate to call model full_clean
class ModelSerializer(serializers.ModelSerializer):
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
            elif meta_fields and field not in meta_fields:
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


class UserSerializer(FlexFieldsSerializerMixin, ModelSerializer):
    class Meta:
        model = User
        exclude = ["preferences"]
        expandable_fields = {
            "projects": ("NEMO.serializers.ProjectSerializer", {"many": True}),
            "managed_projects": ("NEMO.serializers.ProjectSerializer", {"many": True}),
            "groups": ("NEMO.serializers.GroupSerializer", {"many": True}),
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


class ProjectSerializer(FlexFieldsSerializerMixin, ModelSerializer):
    principal_investigators = PrimaryKeyRelatedField(source="manager_set.all", many=True, read_only=True)

    class Meta:
        model = Project
        fields = "__all__"
        expandable_fields = {
            "account": "NEMO.serializers.AccountSerializer",
            "only_allow_tools": ("NEMO.serializers.ToolSerializer", {"many": True}),
            "principal_investigators": ("NEMO.serializers.UserSerializer", {"source": "manager_set", "many": True}),
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
            "descendant": "NEMO.serializers.ReservationSerializer",
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
    question_data = serializers.JSONField(source="question_data_json", allow_null=True, required=False)
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
        }


class StaffChargeSerializer(FlexFieldsSerializerMixin, ModelSerializer):
    class Meta:
        model = StaffCharge
        fields = "__all__"
        expandable_fields = {
            "customer": "NEMO.serializers.UserSerializer",
            "staff_member": "NEMO.serializers.UserSerializer",
            "project": "NEMO.serializers.ProjectSerializer",
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
        }


class ContentTypeSerializer(ModelSerializer):
    class Meta:
        model = ContentType
        fields = "__all__"


class PermissionSerializer(FlexFieldsSerializerMixin, ModelSerializer):
    class Meta:
        model = Permission
        fields = "__all__"
        expandable_fields = {
            "content_type": "NEMO.serializers.ContentTypeSerializer",
        }


class GroupSerializer(FlexFieldsSerializerMixin, ModelSerializer):
    class Meta:
        model = Group
        fields = "__all__"
        expandable_fields = {
            "permissions": ("NEMO.serializers.PermissionSerializer", {"many": True}),
        }


class BillableItemSerializer(serializers.Serializer):
    type = ChoiceField(
        ["missed_reservation", "tool_usage", "area_access", "consumable", "staff_charge", "training_session"]
    )
    name = CharField(max_length=200, read_only=True)
    item_id = IntegerField(read_only=True)
    details = CharField(max_length=500, read_only=True)
    account = CharField(max_length=200, read_only=True)
    account_id = IntegerField(read_only=True)
    project = CharField(max_length=200, read_only=True)
    project_id = IntegerField(read_only=True)
    application = CharField(max_length=200, read_only=True)
    user = CharField(max_length=255, read_only=True)
    username = CharField(max_length=200, read_only=True)
    user_id = IntegerField(read_only=True)
    start = DateTimeField(read_only=True)
    end = DateTimeField(read_only=True)
    quantity = DecimalField(read_only=True, decimal_places=2, max_digits=8)

    def update(self, instance, validated_data):
        pass

    def create(self, validated_data):
        pass

    class Meta:
        fields = "__all__"
