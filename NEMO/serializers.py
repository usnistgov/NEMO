from rest_framework.serializers import ModelSerializer

from NEMO.models import User, Project, Account, Reservation, AreaAccessRecord, UsageEvent, Task, TaskHistory, ScheduledOutage, Tool


class UserSerializer(ModelSerializer):
	class Meta:
		model = User
		fields = ('id', 'first_name', 'last_name', 'username', 'date_joined')


class ProjectSerializer(ModelSerializer):
	class Meta:
		model = Project
		fields = ('id', 'name', 'application_identifier', 'active')


class AccountSerializer(ModelSerializer):
	class Meta:
		model = Account
		fields = ('id', 'name', 'active')


class ToolSerializer(ModelSerializer):
	class Meta:
		model = Tool
		fields = '__all__'


class ReservationSerializer(ModelSerializer):
	class Meta:
		model = Reservation
		fields = '__all__'


class UsageEventSerializer(ModelSerializer):
	class Meta:
		model = UsageEvent
		fields = '__all__'


class AreaAccessRecordSerializer(ModelSerializer):
	class Meta:
		model = AreaAccessRecord
		fields = '__all__'


class TaskHistorySerializer(ModelSerializer):
	class Meta:
		model = TaskHistory
		fields = '__all__'


class TaskSerializer(ModelSerializer):
	history = TaskHistorySerializer(many=True, read_only=True)

	class Meta:
		model = Task
		fields = '__all__'


class ScheduledOutageSerializer(ModelSerializer):
	class Meta:
		model = ScheduledOutage
		fields = '__all__'
