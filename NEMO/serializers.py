from rest_framework import serializers

from NEMO.models import User, Project, Account, Reservation, AreaAccessRecord, UsageEvent


class UserSerializer(serializers.HyperlinkedModelSerializer):
	class Meta:
		model = User
		fields = ('id', 'first_name', 'last_name', 'username')


class ProjectSerializer(serializers.HyperlinkedModelSerializer):
	class Meta:
		model = Project
		fields = ('id', 'name', 'application_identifier', 'active')


class AccountSerializer(serializers.HyperlinkedModelSerializer):
	class Meta:
		model = Account
		fields = ('id', 'name', 'active')


class ReservationSerializer(serializers.ModelSerializer):
	class Meta:
		model = Reservation


class UsageEventSerializer(serializers.ModelSerializer):
	class Meta:
		model = UsageEvent


class AreaAccessRecordSerializer(serializers.ModelSerializer):
	class Meta:
		model = AreaAccessRecord
