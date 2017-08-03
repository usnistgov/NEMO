from rest_framework import viewsets

from NEMO.filters import ReservationFilter, UsageEventFilter, AreaAccessRecordFilter
from NEMO.models import User, Project, Account, Reservation, UsageEvent, AreaAccessRecord
from NEMO.serializers import UserSerializer, ProjectSerializer, AccountSerializer, ReservationSerializer, UsageEventSerializer, AreaAccessRecordSerializer


class UserViewSet(viewsets.ReadOnlyModelViewSet):
	queryset = User.objects.all()
	serializer_class = UserSerializer


class ProjectViewSet(viewsets.ReadOnlyModelViewSet):
	queryset = Project.objects.all()
	serializer_class = ProjectSerializer


class AccountViewSet(viewsets.ReadOnlyModelViewSet):
	queryset = Account.objects.all()
	serializer_class = AccountSerializer


class ReservationViewSet(viewsets.ReadOnlyModelViewSet):
	queryset = Reservation.objects.all()
	serializer_class = ReservationSerializer
	filter_class = ReservationFilter


class UsageEventViewSet(viewsets.ReadOnlyModelViewSet):
	queryset = UsageEvent.objects.all()
	serializer_class = UsageEventSerializer
	filter_class = UsageEventFilter


class AreaAccessRecordViewSet(viewsets.ReadOnlyModelViewSet):
	queryset = AreaAccessRecord.objects.all()
	serializer_class = AreaAccessRecordSerializer
	filter_class = AreaAccessRecordFilter
