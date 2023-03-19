from copy import deepcopy

from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from rest_flex_fields.serializers import FlexFieldsSerializerMixin
from rest_framework import serializers
from rest_framework.fields import CharField, ChoiceField, DateTimeField, DecimalField, IntegerField
from rest_framework.utils import model_meta

from NEMO.models import (
	Account,
	AccountType,
	Area,
	AreaAccessRecord,
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
		self.full_clean(instance)
		return attrs

	def full_clean(self, instance, exclude=None, validate_unique=True):
		instance.full_clean(exclude, validate_unique)


class UserSerializer(ModelSerializer):
	class Meta:
		model = User
		fields = "__all__"

	# Special handling to exclude OneToOne user preferences here and add it in create
	def full_clean(self, instance, exclude=None, validate_unique=True):
		if not instance or not instance.id:
			exclude = ["preferences"]
		super().full_clean(instance, exclude, validate_unique)

	def create(self, validated_data):
		instance: User = super().create(validated_data)
		instance.get_preferences()
		return instance


class ProjectDisciplineSerializer(ModelSerializer):
	class Meta:
		model = ProjectDiscipline
		fields = "__all__"


class ProjectSerializer(FlexFieldsSerializerMixin, ModelSerializer):
	class Meta:
		model = Project
		fields = "__all__"
		expandable_fields = {
			"account": "NEMO.serializers.AccountSerializer",
			"only_allow_tools": ("NEMO.serializers.ToolSerializer", {"many": True}),
		}


class AccountTypeSerializer(FlexFieldsSerializerMixin, ModelSerializer):
	class Meta:
		model = AccountType
		fields = "__all__"


class AccountSerializer(FlexFieldsSerializerMixin, ModelSerializer):
	class Meta:
		model = Account
		fields = "__all__"


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


class ReservationSerializer(FlexFieldsSerializerMixin, ModelSerializer):
	question_data = serializers.JSONField(source="question_data_json")

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
