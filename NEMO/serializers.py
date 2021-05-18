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


class ProjectSerializer(ModelSerializer):
	class Meta:
		model = Project
		fields = "__all__"


class AccountSerializer(ModelSerializer):
	class Meta:
		model = Account
		fields = "__all__"


class ToolSerializer(ModelSerializer):
	class Meta:
		model = Tool
		fields = "__all__"


class ReservationSerializer(ModelSerializer):
	class Meta:
		model = Reservation
		fields = "__all__"


class UsageEventSerializer(ModelSerializer):
	class Meta:
		model = UsageEvent
		fields = "__all__"


class AreaAccessRecordSerializer(ModelSerializer):
	class Meta:
		model = AreaAccessRecord
		fields = "__all__"


class TaskHistorySerializer(ModelSerializer):
	class Meta:
		model = TaskHistory
		fields = "__all__"


class TaskSerializer(ModelSerializer):
	history = TaskHistorySerializer(many=True, read_only=True)

	class Meta:
		model = Task
		fields = "__all__"


class ScheduledOutageSerializer(ModelSerializer):
	class Meta:
		model = ScheduledOutage
		fields = "__all__"


class BillableItemSerializer(Serializer):
	type = ChoiceField(["missed_reservation", "tool_usage", "area_access", "consumable", "staff_charge", "training_session"])
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
