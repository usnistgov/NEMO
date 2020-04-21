from datetime import timedelta

from django import template
from django.urls import reverse, NoReverseMatch
from django.utils import timezone
from django.utils.html import escape, format_html
from django.utils.safestring import mark_safe
from pkg_resources import get_distribution, DistributionNotFound

register = template.Library()


@register.filter
def class_name(value):
	return value.__class__.__name__


@register.filter
def is_soon(time):
	""" 'Soon' is defined as within 10 minutes from now. """
	return time <= timezone.now() + timedelta(minutes=10)


@register.filter()
def to_int(value):
	return int(value)


@register.filter
def json_search_base(items_to_search):
	result = "["
	for item in items_to_search:
		result += '{{"name":"{0}", "id":{1}}},'.format(escape(str(item)), item.id)
	result = result.rstrip(",") + "]"
	return mark_safe(result)


@register.simple_tag
def json_search_base_with_extra_fields(items_to_search, *extra_fields):
	"""
	This tag is similar to the json_search_base filter, but adds extra information upon request.
	The type of object is always provided in the JSON output. Thus, you have a heterogeneous collection
	of objects and differentiate them in your JavaScript. The extra fields are only added when an
	object actually has that attribute. Otherwise, the code skips over the request.
	"""
	result = "["
	for item in items_to_search:
		object_type = item.__class__.__name__.lower()
		result += '{{"name":"{0}", "id":"{1}", "type":"{2}"'.format(escape(str(item)), item.id, object_type)
		for x in extra_fields:
			if hasattr(item, x):
				result += ', "{0}":"{1}"'.format(x, getattr(item, x))
		result += "},"
	result = result.rstrip(",") + "]"
	return mark_safe(result)


@register.simple_tag
def navigation_url(url_name, description):
	try:
		return format_html('<li><a href="{}">{}</a></li>', reverse(url_name), description)
	except NoReverseMatch:
		return ""


@register.filter
def get_item(dictionary, key):
	return dictionary.get(key)


dist_version: str = "0"


@register.simple_tag()
def app_version() -> str:
	global dist_version
	if dist_version != "0":
		return dist_version
	else:
		try:
			dist_version = get_distribution("NEMO").version
		except DistributionNotFound:
			# package is not installed
			dist_version = None
			pass
	return dist_version
