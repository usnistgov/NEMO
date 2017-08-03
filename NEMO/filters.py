from django_filters import FilterSet, DateTimeFilter, BooleanFilter

from NEMO.models import Reservation, UsageEvent, AreaAccessRecord


class ReservationFilter(FilterSet):
	start_gte = DateTimeFilter('start', lookup_type='gte')
	start_lt = DateTimeFilter('start', lookup_type='lt')
	missed = BooleanFilter('missed')

	class Meta:
		model = Reservation
		fields = ['start']


class UsageEventFilter(FilterSet):
	start_gte = DateTimeFilter('start', lookup_type='gte')
	start_lt = DateTimeFilter('start', lookup_type='lt')

	class Meta:
		model = UsageEvent
		fields = ['start']


class AreaAccessRecordFilter(FilterSet):
	start_gte = DateTimeFilter('start', lookup_type='gte')
	start_lt = DateTimeFilter('start', lookup_type='lt')

	class Meta:
		model = AreaAccessRecord
		fields = ['start']
