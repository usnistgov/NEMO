import csv
import os
from calendar import monthrange
from datetime import date, datetime, time, timedelta
from email import encoders
from email.mime.base import MIMEBase
from io import BytesIO
from typing import Dict, List, Optional, Set, Tuple, Union

from PIL import Image
from dateutil import parser
from dateutil.parser import parse
from dateutil.rrule import MONTHLY, rrule
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.core.mail import EmailMessage
from django.db.models import QuerySet
from django.http import HttpResponse
from django.utils import timezone
from django.utils.formats import date_format, time_format
from django.utils.timezone import is_naive, localtime


class BasicDisplayTable(object):
	""" Utility table to make adding headers and rows easier, and export to csv """

	def __init__(self):
		# headers is a list of tuples (key, display)
		self.headers: List[Tuple[str, str]] = []
		# rows is a list of dictionaries. Each dictionary is a row, with keys corresponding to header keys
		self.rows: List[Dict] = []

	def add_header(self, header: Tuple[str, str]):
		if not any(k[0] == header[0] for k in self.headers):
			self.headers.append((header[0], header[1].capitalize()))

	def add_row(self, row: Dict):
		self.rows.append(row)

	def flat_headers(self) -> List[str]:
		return [display for key, display in self.headers]

	def flat_rows(self) -> List[List]:
		flat_result = []
		for row in self.rows:
			flat_result.append([row.get(key, "") for key, display_value in self.headers])
		return flat_result

	def to_csv(self) -> HttpResponse:
		response = HttpResponse(content_type="text/csv")
		writer = csv.writer(response)
		writer.writerow([display_value.capitalize() for key, display_value in self.headers])
		for row in self.rows:
			writer.writerow([row.get(key, "") for key, display_value in self.headers])
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
	)


def parse_start_and_end_date(start, end):
	start = timezone.make_aware(parser.parse(start), timezone.get_current_timezone())
	end = timezone.make_aware(parser.parse(end), timezone.get_current_timezone())
	end += timedelta(days=1, seconds=-1)  # Set the end date to be midnight by adding a day.
	return start, end


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
	result = list(rrule(MONTHLY, dtstart=since, count=month_count))
	result = localize(result)
	result.reverse()
	return result


def get_month_timeframe(date=None):
	if date:
		start = parse(date)
	else:
		start = timezone.now()
	first_of_the_month = localize(datetime(start.year, start.month, 1))
	last_of_the_month = localize(
		datetime(start.year, start.month, monthrange(start.year, start.month)[1], 23, 59, 59, 999999)
	)
	return first_of_the_month, last_of_the_month


def extract_times(parameters, input_timezone=None, start_required=True, end_required=True) -> Tuple[datetime, datetime]:
	"""
	Extract the "start" and "end" parameters from an HTTP request while performing a few logic validation checks.
	The function assumes the UNIX timestamp is in the local timezone. Use input_timezone to specify the timezone.
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
		new_start = localize(new_start, input_timezone)
	except:
		if start or start_required:
			raise Exception("The request parameters did not have a valid start time.")

	try:
		new_end = float(end)
		new_end = datetime.utcfromtimestamp(new_end)
		new_end = localize(new_end, input_timezone)
	except:
		if end or end_required:
			raise Exception("The request parameters did not have a valid end time.")

	if start and end and start_required and end_required and new_end < new_start:
		raise Exception("The request parameters have an end time that precedes the start time.")

	return new_start, new_end


def extract_date(date):
	return localize(datetime.strptime(date, "%Y-%m-%d"))


def extract_dates(parameters):
	"""
	Extract the "start" and "end" parameters from an HTTP request while performing a few logic validation checks.
	"""
	try:
		start = parameters["start"]
	except:
		raise Exception("The request parameters did not contain a start time.")

	try:
		end = parameters["end"]
	except:
		raise Exception("The request parameters did not contain an end time.")

	try:
		start = extract_date(start)
	except:
		raise Exception("The request parameters did not have a valid start time.")

	try:
		end = extract_date(end)
	except:
		raise Exception("The request parameters did not have a valid end time.")

	if end < start:
		raise Exception("The request parameters have an end time that precedes the start time.")

	return start, end


def format_daterange(start_time, end_time, dt_format="DATETIME_FORMAT", d_format="DATE_FORMAT", t_format="TIME_FORMAT", date_separator=" from ", time_separator=" to ") -> str:
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
	if isinstance(universal_time, time):
		return time_format(local_time, df or "TIME_FORMAT", use_l10n)
	elif isinstance(universal_time, datetime):
		return date_format(local_time, df or "DATETIME_FORMAT", use_l10n)
	return date_format(local_time, df or "DATE_FORMAT", use_l10n)


def export_format_datetime(date_time=None, d_format=True, t_format=True, underscore=True, as_current_timezone=True) -> str:
	""" This function returns a formatted date/time for export files. Default returns date + time format, with underscores """
	this_time = date_time if date_time else timezone.now() if as_current_timezone else datetime.now()
	export_date_format = getattr(settings, 'EXPORT_DATE_FORMAT', 'm_d_Y').replace("-", "_")
	export_time_format = getattr(settings, 'EXPORT_TIME_FORMAT', 'h_i_s').replace("-", "_")
	if not underscore:
		export_date_format = export_date_format.replace("_", "-")
		export_time_format = export_time_format.replace("_", "-")
	separator = "-" if underscore else "_"
	datetime_format = export_date_format if d_format and not t_format else export_time_format if not d_format and t_format else export_date_format + separator + export_time_format
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
	""" Returns the BEGINNING of today's day (12:00:00.000000 AM of the current day) in LOCAL time. """
	midnight = t.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
	return localize(midnight) if in_local_timezone else midnight


def end_of_the_day(t: datetime, in_local_timezone=True) -> datetime:
	""" Returns the END of today's day (11:59:59.999999 PM of the current day) in LOCAL time. """
	midnight = t.replace(hour=23, minute=59, second=59, microsecond=999999, tzinfo=None)
	return localize(midnight) if in_local_timezone else midnight


def remove_duplicates(iterable: Union[List, Set, Tuple]) -> Optional[List]:
	if not iterable:
		return None
	if isinstance(iterable, str):
		raise TypeError('argument must be a list, set or tuple')
	return list(set(iterable))


def send_mail(subject, content, from_email, to=None, bcc=None, cc=None, attachments=None, email_category: EmailCategory = EmailCategory.GENERAL, fail_silently=True) -> int:
	try:
		clean_to = remove_duplicates(to)
		clean_bcc = remove_duplicates(bcc)
		clean_cc = remove_duplicates(cc)
	except TypeError:
		raise TypeError('to, cc and bcc arguments must be a list, set or tuple')
	mail = EmailMessage(subject=subject, body=content, from_email=from_email, to=clean_to, bcc=clean_bcc, cc=clean_cc, attachments=attachments)
	mail.content_subtype = "html"
	msg_sent = 0
	if mail.recipients():
		email_record = create_email_log(mail, email_category)
		try:
			msg_sent = mail.send()
		except:
			email_record.ok = False
			if not fail_silently:
				raise
		finally:
			email_record.save()
	return msg_sent


def create_email_log(email: EmailMessage, email_category: EmailCategory):
	from NEMO.models import EmailLog

	email_record: EmailLog = EmailLog.objects.create(category=email_category, sender=email.from_email, to=", ".join(email.recipients()), subject=email.subject, content=email.body)
	if email.attachments:
		email_attachments = []
		for attachment in email.attachments:
			if isinstance(attachment, MIMEBase):
				email_attachments.append(attachment.get_filename() or "")
		if email_attachments:
			email_record.attachments = ", ".join(email_attachments)
	return email_record


def create_email_attachment(stream, filename=None, maintype="application", subtype="octet-stream", **content_type_params) -> MIMEBase:
	attachment = MIMEBase(maintype, subtype, **content_type_params)
	attachment.set_payload(stream.read())
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
		TaskImages.objects.filter(task__tool=task.tool, uploaded_at__year=now.year, uploaded_at__month=now.month, uploaded_at__day=now.day).count()	+ 1
	)
	ext = os.path.splitext(filename)[1]
	return f"task_images/{year}/{tool_name}/{date}_{tool_name}_{number}{ext}"


def get_tool_image_filename(tool, filename):
	from django.template.defaultfilters import slugify

	tool_name = slugify(tool)
	ext = os.path.splitext(filename)[1]
	return f"tool_images/{tool_name}{ext}"


def get_tool_document_filename(tool_documents, filename):
	from django.template.defaultfilters import slugify

	tool_name = slugify(tool_documents.tool)
	return f"tool_documents/{tool_name}/{filename}"


def resize_image(image: InMemoryUploadedFile, max: int, quality=85) -> InMemoryUploadedFile:
	""" Returns a resized image based on the given maximum size """
	with Image.open(image) as img:
		width, height = img.size
		# no need to resize if width or height is already less than the max
		if width <= max or height <= max:
			return image
		if width > height:
			width_ratio = max / float(width)
			new_height = int((float(height) * float(width_ratio)))
			img = img.resize((max, new_height), Image.ANTIALIAS)
		else:
			height_ratio = max / float(height)
			new_width = int((float(width) * float(height_ratio)))
			img = img.resize((new_width, max), Image.ANTIALIAS)
		with BytesIO() as buffer:
			img.save(fp=buffer, format="PNG", quality=quality)
			resized_image = ContentFile(buffer.getvalue())
	file_name_without_ext = os.path.splitext(image.name)[0]
	return InMemoryUploadedFile(
		resized_image, "ImageField", "%s.png" % file_name_without_ext, "image/png", resized_image.tell(), None
	)


def distinct_qs_value_list(qs: QuerySet, field_name: str) -> Set:
	return set(list(qs.values_list(field_name, flat=True)))
