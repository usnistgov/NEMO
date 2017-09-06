from rest_framework import serializers

from NEMO.models import User, Project, Account, Reservation, AreaAccessRecord, UsageEvent


class UserSerializer(serializers.ModelSerializer):
	class Meta:
		model = User
		fields = ('id', 'first_name', 'last_name', 'username')


class ProjectSerializer(serializers.ModelSerializer):
	class Meta:
		model = Project
		fields = ('id', 'name', 'application_identifier', 'active')


class AccountSerializer(serializers.ModelSerializer):
	class Meta:
		model = Account
		fields = ('id', 'name', 'active')


class ReservationSerializer(serializers.ModelSerializer):
	class Meta:
		model = Reservation
		fields = '__all__'


class UsageEventSerializer(serializers.ModelSerializer):
	class Meta:
		model = UsageEvent
		fields = '__all__'


class AreaAccessRecordSerializer(serializers.ModelSerializer):
	class Meta:
		model = AreaAccessRecord
		fields = '__all__'
