import datetime
from datetime import timedelta

from django import template
from django.template import Context, Template
from django.template.defaultfilters import date, time
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.utils.html import escape, format_html
from django.utils.safestring import mark_safe
from pkg_resources import DistributionNotFound, get_distribution

from NEMO.views.customization import get_customization

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


@register.filter()
def to_date(value, arg=None):
	if value in (None, ''):
		return ''
	if isinstance(value, (datetime.datetime, datetime.date)):
		return date(value, arg)
	if isinstance(value, datetime.time):
		return time(value, arg)
	return value


@register.filter
def json_search_base(items_to_search, display = "__str__"):
	result = "["
	for item in items_to_search:
		attr = getattr(item, display, None)
		display_value = attr() if callable(attr) else attr
		result += '{{"name":"{0}", "id":{1}}},'.format(escape(display_value), item.id)
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


@register.simple_tag
def res_question_tbody(dictionary):
	input_dict = dictionary[list(dictionary.keys())[0]]
	headers = list(input_dict.keys())
	header_cells = ''.join([format_html('<th>{}</th>', h) for h in headers])
	head_html = format_html('<thead><tr><th>#</th>{}</tr></thead>', mark_safe(header_cells))

	rows = []
	for i, (index, d) in enumerate(dictionary.items()):
		data_cells_html = ''.join([format_html("<td>{}</td>", d[h]) for h in headers])
		row_html = format_html('<tr><th>{}</th>{}</tr>', i + 1, mark_safe(data_cells_html))
		rows.append(row_html)
	body_html = format_html('<tbody>{}</tbody>', mark_safe(''.join(rows)))
	return head_html + body_html


@register.filter
def get_item(dictionary, key):
	return dictionary.get(key)


@register.simple_tag
def project_selection_display(project):
	project_selection_template = get_customization('project_selection_template')
	contents = "{{ project.name }}"
	try:
		contents = Template(project_selection_template).render(Context({'project': project}))
	except:
		pass
	return format_html(contents)


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
