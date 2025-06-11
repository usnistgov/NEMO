from __future__ import annotations

import csv
import importlib
import os
from calendar import monthrange
from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
from email import encoders
from email.mime.base import MIMEBase
from enum import Enum
from io import BytesIO, StringIO
from logging import getLogger
from smtplib import SMTPAuthenticationError, SMTPConnectError, SMTPServerDisconnected
from typing import Any, Dict, Iterator, List, Optional, Sequence, Set, TYPE_CHECKING, Tuple, Union
from urllib.parse import urljoin

from PIL import Image
from dateutil import rrule
from dateutil.parser import parse
from django.apps import apps
from django.conf import global_settings, settings
from django.contrib.admin import ModelAdmin
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ObjectDoesNotExist
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.core.mail import EmailMessage
from django.db import OperationalError
from django.db.models import FileField, IntegerChoices, QuerySet
from django.http import HttpRequest, HttpResponse, QueryDict
from django.shortcuts import resolve_url
from django.template import Template
from django.template.context import make_context
from django.urls import NoReverseMatch, reverse
from django.utils import timezone as django_timezone
from django.utils.formats import date_format, get_format, time_format
from django.utils.html import format_html
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

# For backwards compatibility
import NEMO.plugins.utils

render_combine_responses = NEMO.plugins.utils.render_combine_responses

if TYPE_CHECKING:
    from NEMO.models import User

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

py_to_pick_date_formats = {
    "%A": "dddd",
    "%a": "ddd",
    "%B": "mmmm",
    "%b": "mmm",
    "%d": "dd",
    "%H": "HH",
    "%I": "hh",
    "%M": "i",
    "%m": "mm",
    "%p": "A",
    "%X": "HH:i",
    "%x": "mm/dd/yyyy",
    "%Y": "yyyy",
    "%y": "yy",
    "%%": "%",
}

UNSET = object()


# Convert a python format string to javascript format string
def convert_py_format_to_js(string_format: str) -> str:
    for py, js in py_to_js_date_formats.items():
        string_format = js.join(string_format.split(py))
    return string_format


def convert_py_format_to_pickadate(string_format: str) -> str:
    string_format = (
        string_format.replace("%w", "")
        .replace("%s", "")
        .replace("%f", "")
        .replace("%:z", "")
        .replace("%z", "")
        .replace("%Z", "")
        .replace("%j", "")
        .replace(":%S", "")
        .replace("%S", "")
        .replace("%U", "")
        .replace("%W", "")
        .replace("%c", "")
        .replace("%G", "")
        .replace("%u", "")
        .replace("%V", "")
    )
    for py, pick in py_to_pick_date_formats.items():
        string_format = pick.join(string_format.split(py))
    return string_format


class DelimiterSeparatedListConverter:
    """
    DelimiterSeparatedListConverter is a utility class for handling conversion
    between delimited strings and Python list objects. It facilitates easy
    serialization and deserialization of data types that use custom delimiters.

    This class is useful in scenarios where data needs to be stored or transmitted
    as delimited strings, such as in a database or a configuration file, and later
    retrieved and manipulated as Python list objects.
    """

    def __init__(self, separator=",", *args, **kwargs):
        self.separator = separator
        super().__init__(*args, **kwargs)

    def to_list(self, value) -> List:
        if value is None:
            return []
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            return [item.strip() for item in value.split(self.separator) if item.strip()]
        # Handle unexpected input types gracefully
        raise ValueError("Invalid value for {}".format(self.__class__.__name__))

    def to_string(self, value) -> str:
        if value is None:
            return ""
        if isinstance(value, list):
            return self.separator.join(map(str, value))
        # Handle other potential cases like single values
        return str(value)


time_input_format = get_format("TIME_INPUT_FORMATS")[0]
date_input_format = get_format("DATE_INPUT_FORMATS")[0]
datetime_input_format = get_format("DATETIME_INPUT_FORMATS")[0]
time_input_js_format = convert_py_format_to_js(time_input_format)
date_input_js_format = convert_py_format_to_js(date_input_format)
datetime_input_js_format = convert_py_format_to_js(datetime_input_format)
pickadate_date_format = getattr(settings, "PICKADATE_DATE_FORMAT", convert_py_format_to_pickadate(date_input_format))
pickadate_time_format = getattr(settings, "PICKADATE_TIME_FORMAT", convert_py_format_to_pickadate(time_input_format))

supported_embedded_video_extensions = [".mp4", ".ogv", ".webm", ".3gp"]
supported_embedded_pdf_extensions = [".pdf"]
supported_embedded_extensions = supported_embedded_pdf_extensions + supported_embedded_video_extensions
CommaSeparatedListConverter = DelimiterSeparatedListConverter()


# Class for Project Applications that can be used for autocomplete
class ProjectApplication(object):
    def __init__(self, name):
        self.name = name
        self.id = name

    def __str__(self):
        return self.name


# Class for Tool Categories that can be used for autocomplete
class ToolCategory(ProjectApplication):
    pass


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
        return self.to_csv_stream(HttpResponse(content_type="text/csv"))

    def to_csv_http_response(self, filename) -> HttpResponse:
        response: HttpResponse = self.to_csv_stream(HttpResponse(content_type="text/csv"))
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    def to_csv_file(self) -> bytes:
        with StringIO() as file_stream:
            file_bytes = self.to_csv_stream(file_stream)
            file_bytes.seek(0)
            return file_bytes.read()

    def to_csv_attachment(self, filename) -> MIMEBase:
        attachment = MIMEBase("text", "csv")
        attachment.set_payload(self.to_csv_file())
        attachment.set_charset("utf-8")
        encoders.encode_base64(attachment)
        attachment.add_header("Content-Disposition", "attachment", filename=filename)
        return attachment

    def to_csv_stream(self, stream):
        writer = csv.writer(stream)
        writer.writerow([capitalize(display_value) for key, display_value in self.headers])
        for row in self.rows:
            writer.writerow([self.formatted_value(row.get(key, "")) for key, display_value in self.headers])
        return stream


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


class EmailCategory(IntegerChoices):
    GENERAL = 0, _("General")
    SYSTEM = 1, _("System")
    DIRECT_CONTACT = 2, _("Direct Contact")
    BROADCAST_EMAIL = 3, _("Broadcast Email")
    TIMED_SERVICES = 4, _("Timed Services")
    FEEDBACK = 5, _("Feedback")
    ABUSE = 6, _("Abuse")
    SAFETY = 7, _("Safety")
    TASKS = 8, _("Tasks")
    ACCESS_REQUESTS = 9, _("Access Requests")
    SENSORS = 10, _("Sensors")
    ADJUSTMENT_REQUESTS = 11, _("Adjustment Requests")
    TRAINING = 12, _("Training")
    ACCESS_EXPIRATION_REMINDERS = 13, _("Access Expiration Reminders")


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
    month_count = (django_timezone.now().year - since.year) * 12 + (django_timezone.now().month - since.month) + 1
    result = list(rrule.rrule(rrule.MONTHLY, dtstart=since, count=month_count))
    result = localize(result)
    result.reverse()
    return result


def get_month_timeframe(date_str: str = None):
    if date_str:
        start = parse(date_str)
    else:
        start = django_timezone.now()
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
    this_time = universal_time if universal_time else django_timezone.now() if as_current_timezone else datetime.now()
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
    this_time = date_time if date_time else django_timezone.now() if as_current_timezone else datetime.now()
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
    naive = type(dt) == date or django_timezone.is_naive(dt)
    return django_timezone.localtime(dt) if not naive else dt


def localize(dt, tz=None):
    tz = tz or django_timezone.get_current_timezone()
    if isinstance(dt, list):
        return [django_timezone.make_aware(d, tz) for d in dt]
    else:
        return django_timezone.make_aware(dt, tz)


def naive_local_current_datetime():
    return django_timezone.localtime(django_timezone.now()).replace(tzinfo=None)


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
            # retry once if we get one of the connection errors
            for i in range(2):
                try:
                    msg_sent = mail.send()
                    break
                except (SMTPServerDisconnected, SMTPConnectError, SMTPAuthenticationError) as e:
                    if i == 0:
                        utilities_logger.exception(str(e))
                        utilities_logger.warning(f"Email sending got an error, retrying once")
                    else:
                        utilities_logger.warning(f"Retrying didn't work")
                        raise
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


def get_model_instance(content_type: ContentType, object_id: int):
    try:
        model = apps.get_model(content_type.app_label, content_type.model)
        return model.objects.get(pk=object_id)
    except (ObjectDoesNotExist, LookupError, AttributeError):
        return None


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
    user: User,
    organizer: User = None,
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
    start = start.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    end = end.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
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


def new_model_copy(instance):
    new_instance = deepcopy(instance)
    new_instance.id = None
    new_instance.pk = None
    new_instance._state.adding = True
    return new_instance


def slugify_underscore(name: Any):
    # Slugify and replaces dashes by underscores
    return slugify(name).replace("-", "_")


def strtobool(val):
    """Convert a string representation of truth to true (1) or false (0).

    True values are 'y', 'yes', 't', 'true', 'on', and '1'; false values
    are 'n', 'no', 'f', 'false', 'off', and '0'.  Raises ValueError if
    'val' is anything else.
    """
    val = val.lower()
    if val in ("y", "yes", "t", "true", "on", "1"):
        return 1
    elif val in ("n", "no", "f", "false", "off", "0"):
        return 0
    else:
        raise ValueError("invalid truth value %r" % (val,))


# This method will subtract weekend time if applicable and weekdays time between weekday_start_time_off and weekday_end_time_off
def get_duration_with_off_schedule(
    start: datetime,
    end: datetime,
    weekend_off: bool,
    policy_off_times: bool,
    weekday_start_time_off: time,
    weekday_end_time_off: time,
) -> timedelta:
    duration = end - start
    local_start, local_end = start.astimezone(), end.astimezone()
    current_date = beginning_of_the_day(local_start)
    while current_date <= local_end:
        begin = beginning_of_the_day(current_date)
        midnight = beginning_of_the_day(current_date + timedelta(days=1))
        current_start, current_end = max(begin, local_start), min(midnight, local_end)
        if current_date.weekday() in [5, 6] and weekend_off:
            # If it's a weekend day and weekends are off, subtract the days' duration
            duration = duration - (current_end - current_start)
        elif (
            current_date.weekday() not in [5, 6]
            and policy_off_times
            and weekday_start_time_off
            and weekday_end_time_off
        ):
            # we have time offs during weekdays
            if weekday_start_time_off < weekday_end_time_off != midnight:
                duration = duration - find_overlapping_duration(
                    current_date, current_start, current_end, weekday_start_time_off, weekday_end_time_off
                )
            else:
                # reverse time off with overnight. i.e. 6pm -> 6am
                # we are just splitting into 2 and running same algorithm
                duration = duration - find_overlapping_duration(
                    current_date, current_start, current_end, weekday_start_time_off, time.min
                )
                duration = duration - find_overlapping_duration(
                    current_date, current_start, current_end, time.min, weekday_end_time_off
                )
        current_date += timedelta(days=1)

    return duration


# given a date, a start and end time and a start time of day and end time of day
# return the overlapping duration
def find_overlapping_duration(
    current_date: datetime,
    current_start: datetime,
    current_end: datetime,
    weekday_start_time_off: time,
    weekday_end_time_off: time,
) -> timedelta:
    current_start_time_off, current_end_time_off = get_local_date_times_for_item_policy_times(
        current_date, weekday_start_time_off, weekday_end_time_off
    )
    # double-check the start or end time off is actually included in the date range
    if current_start <= current_start_time_off < current_end or current_start < current_end_time_off <= current_end:
        return min(current_end, current_end_time_off) - max(current_start, current_start_time_off)
    return timedelta(0)


# This method return datetime objects for start and end date of a policy off range
# i.e. given Fri, Sep 20 and policy off 6pm -> 9pm it will return (Fri Sep 20 @ 6pm, Fri Sep 20 @ 9pm)
# if the policy is overnight (6pm -> 6am) it will return (Fri Sep 20 @ 6pm, Sat Sep 21 @ 6am)
def get_local_date_times_for_item_policy_times(
    current_date: datetime, weekday_start_time_off: time, weekday_end_time_off: time
) -> (datetime, datetime):
    # Convert to local time since we will be using .date()
    current_date = current_date.astimezone()
    current_start_time_off = datetime.combine(current_date.date(), weekday_start_time_off, tzinfo=current_date.tzinfo)
    if weekday_end_time_off < weekday_start_time_off:
        # If the end is before the start, add a day so it counts as overnight
        current_end_time_off = datetime.combine(
            (current_date + timedelta(days=1)).date(), weekday_end_time_off, tzinfo=current_date.tzinfo
        )
    else:
        current_end_time_off = datetime.combine(current_date.date(), weekday_end_time_off, tzinfo=current_date.tzinfo)
    return current_start_time_off, current_end_time_off


def response_js_redirect(to, query_string=None, *args, **kwargs):
    return HttpResponse(
        f"<script>window.location.href = '{resolve_url(to, *args, **kwargs)}?{query_string or ''}';</script>",
        content_type="text/javascript",
        status=202,
    )


def split_into_chunks(iterable: Set, chunk_size: int) -> Iterator[List]:
    """
    Splits a set into chunks of the specified size.
    """
    iterable = list(iterable)  # Convert set to list to support slicing
    for i in range(0, len(iterable), chunk_size):
        yield iterable[i : i + chunk_size]


def copy_media_file(old_file_name, new_file_name, delete_old=False):
    """
    Copies a media file from an old file name to a new file name in the storage.

    Args:
        old_file_name (str): The name of the file to be copied.
        new_file_name (str): The name of the new file to save. If it is the same as old_file_name, no new file is created.
        delete_old (bool): Determines if the old file should be deleted after copying. Defaults to False.
    """
    if default_storage.exists(old_file_name):
        if new_file_name and new_file_name != old_file_name:
            # Save new file if it's different
            with default_storage.open(old_file_name, "rb") as file:
                default_storage.save(new_file_name, file)
        if delete_old and (not new_file_name or new_file_name != old_file_name):
            # Delete old file if no new file name is provided or if it was different
            default_storage.delete(old_file_name)


def update_media_file_on_model_update(instance, file_field_name):
    """
    Ensures that when updating a model instance with a file field, the old file associated with
    the field is appropriately handled. If the new file is different from the old one, the old file
    is deleted. If the file name changes but the file content remains the same, the file is renamed.

    Parameters:
        instance (Model): The model instance being updated. Must be a valid instance of a Django
        model.

        file_field_name (str): The name of the file field being updated. Must be the attribute name
        of a FileField in the model.

    Raises:
        TypeError: If the field specified by `file_field_name` is not a FileField.
    """
    model_class = type(instance)
    field_instance = model_class._meta.get_field(file_field_name)
    if not isinstance(field_instance, FileField):
        raise TypeError(f"Field {file_field_name} is not a FileField")

    if not instance.pk:
        return

    try:
        old_file = getattr(model_class.objects.get(pk=instance.pk), file_field_name)
    except (model_class.DoesNotExist, AttributeError):
        return

    if old_file:
        new_file = getattr(instance, file_field_name)
        new_file_name = field_instance.generate_filename(instance, os.path.basename(new_file.name))
        # Account for things like slashes and case sensitivity
        cleaned_old_file_name = os.path.normcase(os.path.normpath(old_file.name))
        cleaned_new_file_name = os.path.normcase(os.path.normpath(new_file_name))
        if old_file != new_file:
            # if new file is different from old file, delete old file
            old_file.delete(save=False)
        elif cleaned_new_file_name != cleaned_old_file_name:
            # if the new filename if different but it's the same file, rename it
            copy_media_file(old_file.name, new_file_name, delete_old=True)
            new_file.name = new_file_name


def safe_lazy_queryset_evaluation(qs: QuerySet, default=UNSET, raise_exception=False) -> Tuple[Any, bool]:
    """
    Safely evaluates a queryset and returns the evaluated queryset or a default value.

    This function attempts to force the evaluation of a Django queryset. In case an
    OperationalError occurs during the evaluation, it can either return a default value or
    raise the exception, based on the provided arguments. Additionally, it logs a warning
    message when the queryset evaluation fails and `raise_exception` is set to False. This
    can be helpful in handling database operational issues more gracefully.

    Parameters:
        qs (QuerySet): The Django queryset to be evaluated.
        default (Any, optional): The default value to return in case of an error. Defaults
            to an unset value (interpreted as an empty list).
        raise_exception (bool, optional): Whether to raise the encountered
            OperationalError or not. Defaults to False.

    Returns:
        Tuple[Any, bool]: A tuple where the first element is the evaluated queryset (or the
        default value in case of an error) and the second element is a boolean flag
        indicating whether an error occurred.

    Raises:
        OperationalError: If `raise_exception` is True and an OperationalError occurs.
    """
    if default is UNSET:
        default = []
    try:
        # force evaluation of queryset
        _ = list(qs)
        return qs, False
    except OperationalError:
        if raise_exception:
            raise
        utilities_logger.warning("Could not fetch queryset", exc_info=True)
        return default, True


def merge_dicts(first_dict: dict, second_dict: dict):
    """Recursively merge two dictionaries."""
    for key, value in second_dict.items():
        if key in first_dict and isinstance(first_dict[key], dict) and isinstance(value, dict):
            merge_dicts(first_dict[key], value)
        else:
            first_dict[key] = deepcopy(value)
    return first_dict


def load_properties_schemas(model_name: str) -> dict:
    """Dynamically load and merge schemas from settings.py and all apps."""

    def get_schemas():
        combined_schemas = {}

        variable_name = f"{model_name.upper()}_PROPERTIES_JSON_SCHEMA"
        # Load schemas from each installed app (from properties_schemas.py)
        for app_config in apps.get_app_configs():
            try:
                module = importlib.import_module(f"{app_config.name}.properties_schemas")
                if hasattr(module, variable_name):
                    combined_schemas = merge_dicts(combined_schemas, getattr(module, variable_name))
            except ModuleNotFoundError:
                # Ignore apps without schemas.py
                continue

        # Load schemas from `settings.py` if defined
        global_schemas = getattr(settings, variable_name, {})
        if isinstance(global_schemas, dict):
            combined_schemas = merge_dicts(combined_schemas, global_schemas)

        return combined_schemas

    return get_schemas()
