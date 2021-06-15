from rest_flex_fields import FlexFieldsModelSerializer
from rest_framework import serializers
from rest_framework.fields import CharField, IntegerField, DateTimeField, ChoiceField, DecimalField
from rest_framework.serializers import Serializer, ModelSerializer

from NEMO.models import (
	User,
	Project,
	Account,
	Reservation,
	AreaAccessRecord,
	UsageEvent,
	Task,
	TaskHistory,
	ScheduledOutage,
	Tool,
	Area,
	TrainingSession,
	StaffCharge,
	Resource,
)


class UserSerializer(ModelSerializer):
	class Meta:
		model = User
		fields = (
			"id",
			"first_name",
			"last_name",
			"username",
			"email",
			"date_joined",
			"badge_number",
			"is_active",
			"is_staff",
			"is_superuser",
			"is_technician",
			"is_service_personnel",
		)


class ProjectSerializer(FlexFieldsModelSerializer):
	class Meta:
		model = Project
		fields = "__all__"
		expandable_fields = {
			"account": "NEMO.serializers.AccountSerializer",
			"only_allow_tools": ("NEMO.serializers.ToolSerializer", {"many": True}),
		}


class AccountSerializer(ModelSerializer):
	class Meta:
		model = Account
		fields = "__all__"


class ToolSerializer(FlexFieldsModelSerializer):
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


class AreaSerializer(FlexFieldsModelSerializer):
	class Meta:
		model = Area
		fields = "__all__"
		expandable_fields = {"parent_area": "NEMO.serializers.AreaSerializer"}


class ReservationSerializer(FlexFieldsModelSerializer):
	question_data = serializers.JSONField(source="question_data_json")

	class Meta:
		model = Reservation
		fields = "__all__"
		expandable_fields = {
			"user": "NEMO.serializers.UserSerializer",
			"creator": "NEMO.serializers.UserSerializer",
			"tool": "NEMO.serializers.ToolSerializer",
			"area": "NEMO.serializers.AreaSerializer",
			"project": "NEMO.serializers.ProjectSerializer",
			"descendant": "NEMO.serializers.ReservationSerializer",
		}


class UsageEventSerializer(FlexFieldsModelSerializer):
	class Meta:
		model = UsageEvent
		fields = "__all__"
		expandable_fields = {
			"user": "NEMO.serializers.UserSerializer",
			"operator": "NEMO.serializers.UserSerializer",
			"tool": "NEMO.serializers.ToolSerializer",
			"project": "NEMO.serializers.ProjectSerializer",
		}


class AreaAccessRecordSerializer(FlexFieldsModelSerializer):
	class Meta:
		model = AreaAccessRecord
		fields = "__all__"
		expandable_fields = {
			"customer": "NEMO.serializers.UserSerializer",
			"area": "NEMO.serializers.AreaSerializer",
			"project": "NEMO.serializers.ProjectSerializer",
			"staff_charge": "NEMO.serializers.StaffChargeSerializer",
		}


class TaskHistorySerializer(FlexFieldsModelSerializer):
	class Meta:
		model = TaskHistory
		fields = "__all__"
		expandable_fields = {"user": "NEMO.serializers.UserSerializer", "task": "NEMO.serializers.TaskSerializer"}


class TaskSerializer(FlexFieldsModelSerializer):
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


class ScheduledOutageSerializer(FlexFieldsModelSerializer):
	class Meta:
		model = ScheduledOutage
		fields = "__all__"
		expandable_fields = {
			"creator": "NEMO.serializers.UserSerializer",
			"tool": "NEMO.serializers.ToolSerializer",
			"area": "NEMO.serializers.AreaSerializer",
			"resource": "NEMO.serializers.ResourceSerializer",
		}


class TrainingSessionSerializer(FlexFieldsModelSerializer):
	class Meta:
		model = TrainingSession
		fields = "__all__"
		expandable_fields = {
			"trainer": "NEMO.serializers.UserSerializer",
			"trainee": "NEMO.serializers.UserSerializer",
			"tool": "NEMO.serializers.ToolSerializer",
			"project": "NEMO.serializers.ProjectSerializer",
		}


class StaffChargeSerializer(FlexFieldsModelSerializer):
	class Meta:
		model = StaffCharge
		fields = "__all__"
		expandable_fields = {
			"customer": "NEMO.serializers.UserSerializer",
			"staff_member": "NEMO.serializers.UserSerializer",
			"project": "NEMO.serializers.ProjectSerializer",
		}


class ResourceSerializer(FlexFieldsModelSerializer):
	class Meta:
		model = Resource
		fields = "__all__"
		expandable_fields = {
			"fully_dependent_tools": ("NEMO.serializers.ToolSerializer", {"many": True}),
			"partially_dependent_tools": ("NEMO.serializers.ToolSerializer", {"many": True}),
			"dependent_areas": ("NEMO.serializers.AreaSerializer", {"many": True}),
		}


class BillableItemSerializer(Serializer):
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
