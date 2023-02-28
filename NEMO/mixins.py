from datetime import timedelta

from django.utils import timezone

from NEMO.utilities import format_datetime


class CalendarDisplayMixin:
	"""
	Inherit from this class to express that a class type can be displayed in the NEMO calendar.
	Calling get_visual_end() will artificially lengthen the end time so the event is large enough to
	be visible and clickable.
	"""

	start = None
	end = None

	def get_visual_end(self):
		if self.end is None:
			return max(self.start + timedelta(minutes=15), timezone.now())
		else:
			return max(self.start + timedelta(minutes=15), self.end)


class BillableItemMixin:
	"""
	Mixin to be used for any billable item, currently only used by adjustment requests
	TODO: refactor billing api and other places to leverage this mixin
	"""
	AREA_ACCESS = "area_access"
	TOOL_USAGE = "tool_usage"

	def get_billable_type(self):
		from NEMO.models import AreaAccessRecord, UsageEvent

		if isinstance(self, AreaAccessRecord):
			return BillableItemMixin.AREA_ACCESS
		elif isinstance(self, UsageEvent):
			return BillableItemMixin.TOOL_USAGE

	def get_display(self):
		df = "SHORT_DATE_FORMAT"
		dtf = "SHORT_DATETIME_FORMAT"
		b_type = self.get_billable_type()
		if b_type == BillableItemMixin.AREA_ACCESS:
			return f"{self.area} access from {format_datetime(self.start, dtf)} to {format_datetime(self.end, dtf)}"
		elif b_type == BillableItemMixin.TOOL_USAGE:
			return f"{self.tool} usage from {format_datetime(self.start, dtf)} to {format_datetime(self.end, dtf)}"
