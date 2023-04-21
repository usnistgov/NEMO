import datetime
from datetime import timedelta
from importlib.metadata import PackageNotFoundError, version

from django import template
from django.contrib.contenttypes.models import ContentType
from django.shortcuts import resolve_url
from django.template import Context, Template
from django.template.defaultfilters import date, time
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.utils.formats import localize_input
from django.utils.html import escape, escapejs, format_html
from django.utils.safestring import mark_safe

from NEMO.mixins import BillableItemMixin
from NEMO.models import User
from NEMO.views.customization import CustomizationBase, ProjectsAccountsCustomization

register = template.Library()


@register.filter
def class_name(value):
	return value.__class__.__name__


@register.filter
def is_soon(time):
	"""'Soon' is defined as within 10 minutes from now."""
	return time <= timezone.now() + timedelta(minutes=10)


@register.filter
def to_int(value):
	return int(value)


@register.filter
def to_date(value, arg=None):
	if value in (None, ""):
		return ""
	if isinstance(value, datetime.date):
		return date(value, arg)
	if isinstance(value, datetime.time):
		return time(value, arg)
	return value


# Function to format input date using python strftime and the date/time input formats from settings
@register.filter
def input_date_format(value, arg=None):
	if value in (None, ""):
		return ""
	return localize_input(value, arg)


@register.filter
def json_search_base(items_to_search, display="__str__"):
	result = "["
	for item in items_to_search:
		attr = getattr(item, display, None)
		display_value = attr() if callable(attr) else attr
		result += '{{"name":"{0}", "id":{1}}},'.format(escape(display_value), item.id)
	result = result.rstrip(",") + "]"
	return mark_safe(result)


@register.simple_tag
def json_search_base_with_extra_fields(items_to_search, *extra_fields, display="__str__"):
	"""
	This tag is similar to the json_search_base filter, but adds extra information upon request.
	The type of object is always provided in the JSON output. Thus, you have a heterogeneous collection
	of objects and differentiate them in your JavaScript. The extra fields are only added when an
	object actually has that attribute. Otherwise, the code skips over the request.
	"""
	result = "["
	for item in items_to_search:
		object_type = item.__class__.__name__.lower()
		attr = getattr(item, display, None)
		item_display = attr() if callable(attr) else attr
		# we need to escape the name and the extra fields in case they contain new lines etc. otherwise it breaks.
		result += '{{"name":"{0}", "id":"{1}", "type":"{2}"'.format(escapejs(item_display), item.id, object_type)
		# remove name just in case it's also given as extra fields (it would clash with search result name)
		for x in [field for field in extra_fields if field != "name"]:
			if hasattr(item, x):
				result += ', "{0}":"{1}"'.format(x, escapejs(getattr(item, x)))
		result += "},"
	result = result.rstrip(",") + "]"
	return mark_safe(result)


@register.simple_tag
def navigation_url(url_name, description, *conditions):
	if not conditions or any(conditions):
		try:
			return format_html('<li><a href="{}">{}</a></li>', reverse(url_name), description)
		except NoReverseMatch:
			pass
	return ""


@register.simple_tag
def res_question_tbody(dictionary):
	input_dict = dictionary[list(dictionary.keys())[0]]
	headers = list(input_dict.keys())
	header_cells = "".join([format_html("<th>{}</th>", h) for h in headers])
	head_html = format_html("<thead><tr><th>#</th>{}</tr></thead>", mark_safe(header_cells))

	rows = []
	for i, (index, d) in enumerate(dictionary.items()):
		data_cells_html = "".join(
			[format_html("<td>{}</td>", ", ".join(d[h]) if isinstance(d.get(h), list) else d.get(h, "")) for h in headers]
		)
		row_html = format_html("<tr><th>{}</th>{}</tr>", i + 1, mark_safe(data_cells_html))
		rows.append(row_html)
	body_html = format_html("<tbody>{}</tbody>", mark_safe("".join(rows)))
	return head_html + body_html


@register.filter
def get_item(dictionary, key):
	return dictionary.get(key)


@register.simple_tag
def project_selection_display(project):
	project_selection_template = ProjectsAccountsCustomization.get("project_selection_template")
	contents = "{{ project.name }}"
	try:
		contents = Template(project_selection_template).render(Context({"project": project}))
	except:
		pass
	return format_html(contents)


dist_version: str = "0"


@register.simple_tag
def app_version() -> str:
	global dist_version
	if dist_version != "0":
		return dist_version
	else:
		try:
			dist_version = version("NEMO")
		except PackageNotFoundError:
			# package is not installed
			dist_version = None
			pass
	return dist_version


@register.filter
def concat(value, arg):
	return str(value) + str(arg)


@register.filter
def customization(customization_key, key):
	return CustomizationBase.get_instance(customization_key).get(key)


@register.filter
def app_installed(app_name):
	from django.apps import apps

	return apps.is_installed(app_name)


@register.filter
def content_type(obj):
	if obj:
		return ContentType.objects.get_for_model(obj)


@register.filter
def billable_display(item: BillableItemMixin, user: User):
	return item.get_display(user) if item else ""


@register.inclusion_tag("snippets/button.html")
def button(value, type="default", size="", icon=None, onclick=None, dismiss="", submit=None, title=None, url="", **kwargs):
	"""
	This tag is useful to provide a consistent button experience throughout the application.
	Button types are "view", "save", "add", "edit", "delete", "export", "warn", "default".
	Button sizes are "xsmall", "small", "medium", "large".
	"""
	# Assume save button is a submit button
	submit = submit if submit is not None else type == "save"
	btn_class = "btn "
	btn_icon = f"glyphicon "
	second_icon = ""
	if size == "xsmall":
		btn_class += "btn-xs "
	elif size == "small":
		btn_class += "btn-sm "
	elif size == "large":
		btn_class += "btn-large "
	if type in ["save", "add"]:
		btn_class += "btn-success"
		second_icon = "glyphicon-plus-sign" if type == "add" else "glyphicon-floppy-save"
	elif type in ["edit", "info"]:
		btn_class += "btn-info"
		second_icon = "glyphicon-edit"
	elif type == "warn":
		btn_class += "btn-warning"
	elif type == "export":
		btn_class += "btn-primary"
		second_icon = "glyphicon-export"
	elif type == "view":
		btn_class += "btn-primary"
		second_icon = "glyphicon-search"
	elif type == "delete":
		btn_class += "btn-danger"
		second_icon = "glyphicon-trash"
	elif type == "default":
		btn_class += "btn-default"
	return {
		"btn_element": "a" if url else "button",
		"btn_value": value,
		"btn_title": value if title is None else title,
		"btn_class": btn_class,
		"btn_icon": btn_icon + second_icon if icon is None else btn_icon + icon,
		"btn_onclick": onclick if onclick is not None else "submit_and_disable(this);" if submit else "",
		"btn_type": None if url else "submit" if submit else "button",
		"btn_url": resolve_url(url) if url else None,
		"btn_dismiss": dismiss,
		"kwargs": kwargs,  # pass the rest of the kwargs directly to the button to be used as attributes
	}
