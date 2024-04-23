import csv
import importlib
import os
from calendar import monthrange
from datetime import date, datetime, time
from email import encoders
from email.mime.base import MIMEBase
from enum import Enum
from io import BytesIO, StringIO
from logging import getLogger
from typing import Dict, List, Optional, Sequence, Set, Tuple, Union
from urllib.parse import urljoin

import pytz
from PIL import Image
from dateutil import rrule
from dateutil.parser import parse
from django.apps import apps
from django.conf import global_settings, settings
from django.contrib.admin import ModelAdmin
from django.contrib.contenttypes.models import ContentType
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.core.mail import EmailMessage
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse, QueryDict
from django.shortcuts import render
from django.template import Template
from django.template.context import make_context
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.utils.formats import date_format, get_format, time_format
from django.utils.html import format_html
from django.utils.text import slugify
from django.utils.timezone import is_naive, localtime

utilities_logger = getLogger(__name__)

# List of python to js formats
py_to_js_date_formats = {
    "%A": "dddd",
    "%a": "ddd",
    "%B": "MMMM",
    "%b": "MMM",
    "%c": "ddd MMM DD HH:mm:ss YYYY",
    "%d": "DD",
    "%f": "SSS",
    "%H": "HH",
    "%I": "hh",
    "%j": "DDDD",
    "%M": "mm",
    "%m": "MM",
    "%p": "A",
    "%S": "ss",
    "%U": "ww",
    "%W": "ww",
    "%w": "d",
    "%X": "HH:mm:ss",
    "%x": "MM/DD/YYYY",
    "%Y": "YYYY",
    "%y": "YY",
    "%Z": "z",
    "%z": "ZZ",
    "%%": "%",
}


# Convert a python format string to javascript format string
def convert_py_format_to_js(string_format: str) -> str:
    for py, js in py_to_js_date_formats.items():
        string_format = js.join(string_format.split(py))
    return string_format


time_input_format = get_format("TIME_INPUT_FORMATS")[0]
date_input_format = get_format("DATE_INPUT_FORMATS")[0]
datetime_input_format = get_format("DATETIME_INPUT_FORMATS")[0]
time_input_js_format = convert_py_format_to_js(time_input_format)
date_input_js_format = convert_py_format_to_js(date_input_format)
datetime_input_js_format = convert_py_format_to_js(datetime_input_format)


supported_embedded_video_extensions = [".mp4", ".ogv", ".webm", ".3gp"]
supported_embedded_pdf_extensions = [".pdf"]
supported_embedded_extensions = supported_embedded_pdf_extensions + supported_embedded_video_extensions


class EmptyHttpRequest(HttpRequest):
    def __init__(self):
        super().__init__()
        self.session = QueryDict(mutable=True)
        self.device = "desktop"


class BasicDisplayTable(object):
    """Utility table to make adding headers and rows easier, and export to csv"""

    def __init__(self):
        self.list_delimiter = ", "
        # headers is a list of tuples (key, display)
        self.headers: List[Tuple[str, str]] = []
        # rows is a list of dictionaries. Each dictionary is a row, with keys corresponding to header keys
        self.rows: List[Dict] = []

    def add_header(self, header: Tuple[str, str]):
        if not any(k[0] == header[0] for k in self.headers):
            self.headers.append((header[0], capitalize(header[1])))

    def add_row(self, row: Dict):
        self.rows.append(row)

    def flat_headers(self) -> List[str]:
        return [display for key, display in self.headers]

    def flat_rows(self) -> List[List]:
        flat_result = []
        for row in self.rows:
            flat_result.append([row.get(key, "") for key, display_value in self.headers])
        return flat_result

    def formatted_value(self, value):
        if value:
            if isinstance(value, time):
                return format_datetime(value, "SHORT_TIME_FORMAT")
            elif isinstance(value, datetime):
                return format_datetime(value, "SHORT_DATETIME_FORMAT")
            elif isinstance(value, date):
                return format_datetime(value, "SHORT_DATE_FORMAT")
            elif isinstance(value, list):
                return self.list_delimiter.join(value)
        return value

    def to_csv(self) -> HttpResponse:
        response = HttpResponse(content_type="text/csv")
        writer = csv.writer(response)
        writer.writerow([capitalize(display_value) for key, display_value in self.headers])
        for row in self.rows:
            writer.writerow([self.formatted_value(row.get(key, "")) for key, display_value in self.headers])
        return response


def bootstrap_primary_color(color_type):
    if color_type == "success":
        return "#5cb85c"
    elif color_type == "info":
        return "#5bc0de"
    elif color_type == "warning":
        return "#f0ad4e"
    elif color_type == "danger":
        return "#d9534f"
    return None


class EmailCategory(object):
    GENERAL = 0
    SYSTEM = 1
    DIRECT_CONTACT = 2
    BROADCAST_EMAIL = 3
    TIMED_SERVICES = 4
    FEEDBACK = 5
    ABUSE = 6
    SAFETY = 7
    TASKS = 8
    ACCESS_REQUESTS = 9
    SENSORS = 10
    ADJUSTMENT_REQUESTS = 11
    Choices = (
        (GENERAL, "General"),
        (SYSTEM, "System"),
        (DIRECT_CONTACT, "Direct Contact"),
        (BROADCAST_EMAIL, "Broadcast Email"),
        (TIMED_SERVICES, "Timed Services"),
        (FEEDBACK, "Feedback"),
        (ABUSE, "Abuse"),
        (SAFETY, "Safety"),
        (TASKS, "Tasks"),
        (ACCESS_REQUESTS, "Access Requests"),
        (SENSORS, "Sensors"),
        (ADJUSTMENT_REQUESTS, "Adjustment Requests"),
    )


class RecurrenceFrequency(Enum):
    DAILY = 1, rrule.DAILY, "Day(s)", "day"
    DAILY_WEEKDAYS = 2, rrule.DAILY, "Week Day(s)", "week day"
    DAILY_WEEKENDS = 3, rrule.DAILY, "Weekend Day(s)", "weekend day"
    WEEKLY = 4, rrule.WEEKLY, "Week(s)", "week"
    MONTHLY = 5, rrule.MONTHLY, "Month(s)", "month"
    YEARLY = 6, rrule.YEARLY, "Year(s)", "year"

    def __new__(cls, *args, **kwargs):
        obj = object.__new__(cls)
        obj._value_ = args[0]
        return obj

    def __init__(self, index: int, rrule_freq, display_value, display_text):
        self.index = index
        self.rrule_freq = rrule_freq
        self.display_value = display_value
        self.display_text = display_text

    @classmethod
    def choices(cls):
        return [(freq.index, freq.display_value) for freq in cls]


def quiet_int(value_to_convert, default_upon_failure=0):
    """
    Attempt to convert the given value to an integer. If there is any problem
    during the conversion, simply return 'default_upon_failure'.
    """
    result = default_upon_failure
    try:
        result = int(value_to_convert)
    except:
        pass
    return result


def parse_parameter_string(
    parameter_dictionary, parameter_key, maximum_length=3000, raise_on_error=False, default_return=""
):
    """
    Attempts to parse a string from an HTTP GET or POST dictionary and applies validation checks.
    """
    try:
        parameter = parameter_dictionary[parameter_key].strip()
        if raise_on_error and len(parameter) > maximum_length:
            raise Exception(
                "The parameter named {} is {} characters long, exceeding the maximum length of {} characters.".format(
                    parameter_key, len(parameter), maximum_length
                )
            )
        return parameter
    except Exception as e:
        if raise_on_error:
            raise e
        return default_return


def month_list(since=datetime(year=2013, month=11, day=1)):
    month_count = (timezone.now().year - since.year) * 12 + (timezone.now().month - since.month) + 1
    result = list(rrule.rrule(rrule.MONTHLY, dtstart=since, count=month_count))
    result = localize(result)
    result.reverse()
    return result


def get_month_timeframe(date_str: str = None):
    if date_str:
        start = parse(date_str)
    else:
        start = timezone.now()
    first_of_the_month = localize(datetime(start.year, start.month, 1))
    last_of_the_month = localize(
        datetime(start.year, start.month, monthrange(start.year, start.month)[1], 23, 59, 59, 999999)
    )
    return first_of_the_month, last_of_the_month


def get_day_timeframe(day_date: datetime.date = None):
    start = day_date
    if not day_date:
        start = date.today()
    start = datetime.combine(start, time())
    return beginning_of_the_day(start), end_of_the_day(start)


def extract_optional_beginning_and_end_dates(parameters, date_only=False, time_only=False):
    """
    Extract the "start" and "end" parameters from an HTTP request
    The dates/times are expected in the input formats set in settings.py and assumed in the server's timezone
    """
    new_parameters = {}
    start = parameters.get("start")
    end = parameters.get("end")
    selected_format = date_input_format if date_only else time_input_format if time_only else datetime_input_format
    new_parameters["start"] = datetime.strptime(start, selected_format).timestamp() if start else None
    new_parameters["end"] = datetime.strptime(end, selected_format).timestamp() if end else None
    return extract_optional_beginning_and_end_times(new_parameters)


def extract_optional_beginning_and_end_times(parameters):
    return extract_times(parameters, start_required=False, end_required=False, beginning_and_end=True)


def extract_times(
    parameters, start_required=True, end_required=True, beginning_and_end=False
) -> Tuple[datetime, datetime]:
    """
    Extract the "start" and "end" parameters from an HTTP request while performing a few logic validation checks.
    The function assumes the UNIX timestamp is in the server's timezone.
    """
    start, end, new_start, new_end = None, None, None, None
    try:
        start = parameters["start"]
    except:
        if start_required:
            raise Exception("The request parameters did not contain a start time.")

    try:
        end = parameters["end"]
    except:
        if end_required:
            raise Exception("The request parameters did not contain an end time.")

    try:
        new_start = float(start)
        new_start = datetime.utcfromtimestamp(new_start)
        new_start = localize(new_start)
        if beginning_and_end:
            new_start = beginning_of_the_day(new_start)
    except:
        if start or start_required:
            raise Exception("The request parameters did not have a valid start time.")

    try:
        new_end = float(end)
        new_end = datetime.utcfromtimestamp(new_end)
        new_end = localize(new_end)
        if beginning_and_end:
            new_end = end_of_the_day(new_end)
    except:
        if end or end_required:
            raise Exception("The request parameters did not have a valid end time.")

    if start and end and start_required and end_required and new_end < new_start:
        raise Exception("The request parameters have an end time that precedes the start time.")

    return new_start, new_end


def format_daterange(
    start_time,
    end_time,
    dt_format="DATETIME_FORMAT",
    d_format="DATE_FORMAT",
    t_format="TIME_FORMAT",
    date_separator=" from ",
    time_separator=" to ",
) -> str:
    # This method returns a formatted date range, using the date only once if it is on the same day
    if isinstance(start_time, time):
        return f"{date_separator}{format_datetime(start_time, t_format)}{time_separator}{format_datetime(end_time, t_format)}".strip()
    elif isinstance(start_time, datetime):
        if as_timezone(start_time).date() != as_timezone(end_time).date():
            return f"{date_separator}{format_datetime(start_time, dt_format)}{time_separator}{format_datetime(end_time, dt_format)}".strip()
        else:
            return f"{format_datetime(start_time, d_format)}{date_separator}{format_datetime(start_time, t_format)}{time_separator}{format_datetime(end_time, t_format)}".strip()
    else:
        return f"{date_separator}{format_datetime(start_time, d_format)}{time_separator}{format_datetime(end_time, d_format)}".strip()


def format_datetime(universal_time=None, df=None, as_current_timezone=True, use_l10n=None) -> str:
    this_time = universal_time if universal_time else timezone.now() if as_current_timezone else datetime.now()
    local_time = as_timezone(this_time) if as_current_timezone else this_time
    if isinstance(local_time, time):
        return time_format(local_time, df or "TIME_FORMAT", use_l10n)
    elif isinstance(local_time, datetime):
        return date_format(local_time, df or "DATETIME_FORMAT", use_l10n)
    return date_format(local_time, df or "DATE_FORMAT", use_l10n)


def export_format_datetime(
    date_time=None, d_format=True, t_format=True, underscore=True, as_current_timezone=True
) -> str:
    """
    This function returns a formatted date/time for export files.
    Default returns date + time format, with underscores
    """
    this_time = date_time if date_time else timezone.now() if as_current_timezone else datetime.now()
    export_date_format = getattr(settings, "EXPORT_DATE_FORMAT", "m_d_Y").replace("-", "_")
    export_time_format = getattr(settings, "EXPORT_TIME_FORMAT", "h_i_s").replace("-", "_")
    if not underscore:
        export_date_format = export_date_format.replace("_", "-")
        export_time_format = export_time_format.replace("_", "-")
    separator = "-" if underscore else "_"
    datetime_format = (
        export_date_format
        if d_format and not t_format
        else export_time_format if not d_format and t_format else export_date_format + separator + export_time_format
    )
    return format_datetime(this_time, datetime_format, as_current_timezone)


def as_timezone(dt):
    naive = type(dt) == date or is_naive(dt)
    return timezone.localtime(dt) if not naive else dt


def localize(dt, tz=None):
    tz = tz or timezone.get_current_timezone()
    if isinstance(dt, list):
        return [tz.localize(d) for d in dt]
    else:
        return tz.localize(dt)


def naive_local_current_datetime():
    return localtime(timezone.now()).replace(tzinfo=None)


def beginning_of_the_day(t: datetime, in_local_timezone=True) -> datetime:
    """Returns the BEGINNING of today's day (12:00:00.000000 AM of the current day) in LOCAL time."""
    zero = t.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    return localize(zero) if in_local_timezone else zero


def end_of_the_day(t: datetime, in_local_timezone=True) -> datetime:
    """Returns the END of today's day (11:59:59.999999 PM of the current day) in LOCAL time."""
    midnight = t.replace(hour=23, minute=59, second=59, microsecond=999999, tzinfo=None)
    return localize(midnight) if in_local_timezone else midnight


def is_date_in_datetime_range(date_to_check: date, start_date: datetime, end_date: datetime) -> bool:
    # use timezone of start_date for date_to_check
    start_of_day = beginning_of_the_day(datetime.combine(date_to_check, time()))
    end_of_day = end_of_the_day(datetime.combine(date_to_check, time()))
    return start_date <= end_of_day and start_of_day <= end_date


def remove_duplicates(iterable: Union[List, Set, Tuple]) -> List:
    if not iterable:
        return []
    if isinstance(iterable, str):
        raise TypeError("argument must be a list, set or tuple")
    return list(set(iterable))


def send_mail(
    subject,
    content,
    from_email,
    to=None,
    bcc=None,
    cc=None,
    attachments=None,
    email_category: EmailCategory = EmailCategory.GENERAL,
    fail_silently=True,
) -> int:
    try:
        clean_to = filter(None, remove_duplicates(to))
        clean_bcc = filter(None, remove_duplicates(bcc))
        clean_cc = filter(None, remove_duplicates(cc))
    except TypeError:
        raise TypeError("to, cc and bcc arguments must be a list, set or tuple")
    user_reply_to = getattr(settings, "EMAIL_USE_DEFAULT_AND_REPLY_TO", False)
    reply_to = None
    if user_reply_to:
        reply_to = [from_email]
        from_email = None
    email_prefix = getattr(settings, "NEMO_EMAIL_SUBJECT_PREFIX", None)
    if email_prefix and not subject.startswith(email_prefix):
        subject = email_prefix + subject
    mail = EmailMessage(
        subject=subject,
        body=content,
        from_email=from_email,
        to=clean_to,
        bcc=clean_bcc,
        cc=clean_cc,
        attachments=attachments,
        reply_to=reply_to,
    )
    mail.content_subtype = "html"
    msg_sent = 0
    if mail.recipients():
        email_record = create_email_log(mail, email_category)
        try:
            msg_sent = mail.send()
        except Exception as e:
            email_record.ok = False
            if not fail_silently:
                raise
            else:
                utilities_logger.error(e)
        finally:
            email_record.save()
    return msg_sent


def create_email_log(email: EmailMessage, email_category: EmailCategory):
    from NEMO.models import EmailLog

    email_record: EmailLog = EmailLog.objects.create(
        category=email_category,
        sender=email.from_email,
        to=", ".join(email.recipients()),
        subject=email.subject,
        content=email.body,
    )
    if email.attachments:
        email_attachments = []
        for attachment in email.attachments:
            if isinstance(attachment, MIMEBase):
                email_attachments.append(attachment.get_filename() or "")
            else:
                email_attachments.append(attachment[0] or "")
        if email_attachments:
            email_record.attachments = ", ".join(email_attachments)
    return email_record


def create_email_attachment(
    stream, filename=None, maintype="application", subtype="octet-stream", **content_type_params
) -> MIMEBase:
    attachment = MIMEBase(maintype, subtype, **content_type_params)
    attachment.set_payload(stream.read())
    if maintype == "text":
        attachment.set_charset("utf-8")
    encoders.encode_base64(attachment)
    if filename:
        attachment.add_header("Content-Disposition", f'attachment; filename="{filename}"')
    return attachment


def get_task_image_filename(task_images, filename):
    from NEMO.models import Task, TaskImages
    from django.template.defaultfilters import slugify

    task: Task = task_images.task
    tool_name = slugify(task.tool)
    now = datetime.now()
    date = export_format_datetime(now, t_format=False, as_current_timezone=False)
    year = now.strftime("%Y")
    number = "{:02d}".format(
        TaskImages.objects.filter(
            task__tool=task.tool, uploaded_at__year=now.year, uploaded_at__month=now.month, uploaded_at__day=now.day
        ).count()
        + 1
    )
    ext = os.path.splitext(filename)[1]
    return f"task_images/{year}/{tool_name}/{date}_{tool_name}_{number}{ext}"


def get_tool_image_filename(tool, filename):
    from django.template.defaultfilters import slugify

    tool_name = slugify(tool)
    ext = os.path.splitext(filename)[1]
    return f"tool_images/{tool_name}{ext}"


def get_hazard_logo_filename(category, filename):
    from django.template.defaultfilters import slugify

    category_name = slugify(category)
    ext = os.path.splitext(filename)[1]
    return f"chemical_hazard_logos/{category_name}{ext}"


def get_chemical_document_filename(chemical, filename):
    from django.template.defaultfilters import slugify

    chemical_name = slugify(chemical.name)
    return f"chemical_documents/{chemical_name}/{filename}"


def document_filename_upload(instance, filename):
    return instance.get_filename_upload(filename)


def resize_image(image: InMemoryUploadedFile, max_size: int, quality=85) -> InMemoryUploadedFile:
    """Returns a resized image based on the given maximum size"""
    with Image.open(image) as img:
        width, height = img.size
        # no need to resize if width or height is already less than the max
        if width <= max_size or height <= max_size:
            return image
        if width > height:
            width_ratio = max_size / float(width)
            new_height = int((float(height) * float(width_ratio)))
            img = img.resize((max_size, new_height), Image.Resampling.LANCZOS)
        else:
            height_ratio = max_size / float(height)
            new_width = int((float(width) * float(height_ratio)))
            img = img.resize((new_width, max_size), Image.Resampling.LANCZOS)
        with BytesIO() as buffer:
            img.save(fp=buffer, format="PNG", quality=quality)
            resized_image = ContentFile(buffer.getvalue())
    file_name_without_ext = os.path.splitext(image.name)[0]
    return InMemoryUploadedFile(
        resized_image, "ImageField", "%s.png" % file_name_without_ext, "image/png", resized_image.tell(), None
    )


def distinct_qs_value_list(qs: QuerySet, field_name: str) -> Set:
    return set(list(qs.values_list(field_name, flat=True)))


# Useful function to render and combine 2 separate django templates
def render_combine_responses(request, original_response: HttpResponse, template_name, context):
    """Combines contents of an original http response with a new one"""
    additional_content = render(request, template_name, context)
    original_response.content += additional_content.content
    return original_response


def render_email_template(template, dictionary: dict, request=None):
    """Use Django's templating engine to render the email template
    If we don't have a request, create a empty one so context_processors (messages, customizations etc.) can be used
    """
    return Template(template).render(make_context(dictionary, request or EmptyHttpRequest()))


def queryset_search_filter(query_set: QuerySet, search_fields: Sequence, request, display="__str__") -> HttpResponse:
    """
    This function reuses django admin search result to implement our own autocomplete.
    Its usage is the same as ModelAdmin, it needs a base queryset, list of fields and a search query.
    It returns the HttpResponse with json formatted data, ready to use by the autocomplete js code
    """
    if is_ajax(request):
        query = request.GET.get("query", "")
        admin_model = ModelAdmin(query_set.model, None)
        admin_model.search_fields = search_fields
        search_qs, search_use_distinct = admin_model.get_search_results(None, query_set, query)
        if search_use_distinct:
            search_qs = search_qs.distinct()
        from NEMO.templatetags.custom_tags_and_filters import json_search_base_with_extra_fields

        data = json_search_base_with_extra_fields(search_qs, *search_fields, display=display)
    else:
        data = "This request can only be made as an ajax call"
    return HttpResponse(data, "application/json")


def is_ajax(request):
    return request.META.get("HTTP_X_REQUESTED_WITH") == "XMLHttpRequest"


def get_recurring_rule(start: date, frequency: RecurrenceFrequency, until=None, interval=1, count=None) -> rrule:
    by_week_day = None
    if frequency == RecurrenceFrequency.DAILY_WEEKDAYS:
        by_week_day = (rrule.MO, rrule.TU, rrule.WE, rrule.TH, rrule.FR)
    elif frequency == RecurrenceFrequency.DAILY_WEEKENDS:
        by_week_day = (rrule.SA, rrule.SU)
    return rrule.rrule(
        dtstart=start, freq=frequency.rrule_freq, interval=interval, until=until, count=count, byweekday=by_week_day
    )


def get_full_url(location, request=None):
    """
    Function used mainly in emails and places where the request might or might not be available.
    If the request is available, use django's built in way to build the absolute URL, otherwise
    use the SERVER_DOMAIN variable from settings, which defaults to the first ALLOWED_HOSTS value.
    """
    # For lazy locations
    location = str(location)
    if request and not isinstance(request, EmptyHttpRequest):
        return request.build_absolute_uri(location)
    else:
        domain = getattr(settings, "SERVER_DOMAIN", "https://{}".format(settings.ALLOWED_HOSTS[0]))
        return urljoin(domain, location)


def capitalize(string: Optional[str]) -> str:
    """
    This function capitalizes the first letter only. Built-in .capitalize() method does it, but also
    makes the rest of the string lowercase, which is not what we want here
    """
    if not string:
        return string
    return string[0].upper() + string[1:]


def admin_get_item(content_type, object_id):
    """
    This function can be used in django admin to display the item of a generic foreign key with a link
    """
    if not content_type or not object_id:
        return "-"
    app_label, model = content_type.app_label, content_type.model
    viewname = f"admin:{app_label}_{model}_change"
    try:
        args = [object_id]
        link = reverse(viewname, args=args)
    except NoReverseMatch:
        return "-"
    else:
        return format_html('<a href="{}">{} - #{}</a>', link, get_model_name(content_type), object_id)


def get_model_name(content_type: ContentType):
    try:
        model = apps.get_model(content_type.app_label, content_type.model)
        return model._meta.verbose_name.capitalize()
    except (LookupError, AttributeError):
        return ""


def get_email_from_settings() -> str:
    """
    Return the default from email if it has been overriden, otherwise the server email
    This allows admins to specify a different default from email (used for communication)
    from the server email which is more meant for errors and such.
    """
    return (
        settings.DEFAULT_FROM_EMAIL
        if settings.DEFAULT_FROM_EMAIL != global_settings.DEFAULT_FROM_EMAIL
        else settings.SERVER_EMAIL
    )


def get_class_from_settings(setting_name: str, default_value: str):
    setting_class = getattr(settings, setting_name, default_value)
    assert isinstance(setting_class, str)
    pkg, attr = setting_class.rsplit(".", 1)
    ret = getattr(importlib.import_module(pkg), attr)
    return ret()


def create_ics(
    identifier,
    event_name,
    start: datetime,
    end: datetime,
    user,
    organizer=None,
    cancelled: bool = False,
    description: str = None,
) -> MIMEBase:
    from NEMO.views.customization import ApplicationCustomization

    site_title = ApplicationCustomization.get("site_title")
    if organizer:
        organizer_email = organizer.email
        organizer = organizer.get_name()
    else:
        organizer_email = getattr(settings, "RESERVATION_ORGANIZER_EMAIL", "no_reply")
        organizer = getattr(settings, "RESERVATION_ORGANIZER", site_title)
    method_name = "CANCEL" if cancelled else "REQUEST"
    sequence = "SEQUENCE:2\n" if cancelled else "SEQUENCE:0\n"
    priority = "PRIORITY:5\n" if cancelled else "PRIORITY:0\n"
    now = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    start = start.astimezone(pytz.utc).strftime("%Y%m%dT%H%M%SZ")
    end = end.astimezone(pytz.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR\n",
        "VERSION:2.0\n",
        f"METHOD:{method_name}\n",
        "BEGIN:VEVENT\n",
        f"UID:{str(identifier)}\n",
        sequence,
        priority,
        f"DTSTAMP:{now}\n",
        f"DTSTART:{start}\n",
        f"DTEND:{end}\n",
        f'ATTENDEE;CN="{user.get_name()}";RSVP=TRUE:mailto:{user.email}\n',
        f'ORGANIZER;CN="{organizer}":mailto:{organizer_email}\n',
        f"SUMMARY:[{site_title}] {event_name}\n",
        f"DESCRIPTION:{description or ''}\n",
        f"STATUS:{'CANCELLED' if cancelled else 'CONFIRMED'}\n",
        "END:VEVENT\n",
        "END:VCALENDAR\n",
    ]
    ics = StringIO("")
    ics.writelines(lines)
    ics.seek(0)

    attachment = create_email_attachment(ics, maintype="text", subtype="calendar", method=method_name)
    return attachment


def slugify_underscore(name: str):
    # Slugify and replaces dashes by underscores
    return slugify(name).replace("-", "_")
