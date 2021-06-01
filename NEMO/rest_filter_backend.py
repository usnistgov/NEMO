from django_filters import filterset
from django_filters.rest_framework import DjangoFilterBackend
from django_filters.utils import try_dbfield


class NEMOFilterSet(filterset.FilterSet):
	""" This filter set for django rest_frameworks adds support for isempty lookup in GUI """

	@classmethod
	def filter_for_lookup(cls, field, lookup_type):
		DEFAULTS = dict(cls.FILTER_DEFAULTS)
		if hasattr(cls, "_meta"):
			DEFAULTS.update(cls._meta.filter_overrides)

		data = try_dbfield(DEFAULTS.get, field.__class__) or {}
		filter_class = data.get("filter_class")

		# if there is no filter class, exit early
		if not filter_class:
			return None, {}

		if lookup_type == "isempty":
			from django.db import models

			data = try_dbfield(DEFAULTS.get, models.BooleanField)

			filter_class = data.get("filter_class")
			params = data.get("extra", lambda x: {})(field)
			return filter_class, params
		else:
			return super().filter_for_lookup(field, lookup_type)


class NEMOFilterBackend(DjangoFilterBackend):
	filterset_base = NEMOFilterSet
