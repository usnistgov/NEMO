from datetime import timedelta

from django.utils import timezone


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
