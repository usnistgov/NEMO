from django_filters import FilterSet, IsoDateTimeFilter, BooleanFilter
from django_filters.widgets import BooleanWidget

from NEMO.models import Reservation, UsageEvent, AreaAccessRecord, User


class ReservationFilter(FilterSet):
	start_gte = IsoDateTimeFilter('start', lookup_expr='gte')
	start_lt = IsoDateTimeFilter('start', lookup_expr='lt')
	missed = BooleanFilter('missed', widget=BooleanWidget())

	class Meta:
		model = Reservation
		fields = []


class UsageEventFilter(FilterSet):
	start_gte = IsoDateTimeFilter('start', lookup_expr='gte')
	start_lt = IsoDateTimeFilter('start', lookup_expr='lt')

	class Meta:
		model = UsageEvent
		fields = []


class AreaAccessRecordFilter(FilterSet):
	start_gte = IsoDateTimeFilter('start', lookup_expr='gte')
	start_lt = IsoDateTimeFilter('start', lookup_expr='lt')

	class Meta:
		model = AreaAccessRecord
		fields = []


class UserFilter(FilterSet):

	class Meta:
		model = User
		fields = {
			'date_joined': ['month', 'year'],
		}
