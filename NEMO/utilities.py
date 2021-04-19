import csv
import os
from calendar import monthrange
from datetime import timedelta, datetime
from email import encoders
from email.mime.base import MIMEBase
from io import BytesIO
from typing import Tuple, List, Dict, Set

from PIL import Image
from dateutil import parser
from dateutil.parser import parse
from dateutil.rrule import MONTHLY, rrule
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.core.mail import EmailMessage
from django.db.models import QuerySet
from django.http import HttpResponse
from django.utils import timezone
from django.utils.timezone import localtime


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


def format_datetime(universal_time):
	local_time = universal_time.astimezone(timezone.get_current_timezone())
	day = int(local_time.strftime("%d"))
	if 4 <= day <= 20 or 24 <= day <= 30:
		suffix = "th"
	else:
		suffix = ["st", "nd", "rd"][day % 10 - 1]
	return (
			local_time.strftime("%A, %B ")
			+ str(day)
			+ suffix
			+ local_time.strftime(", %Y @ ")
			+ local_time.strftime("%I:%M %p").lstrip("0")
	)


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


def send_mail(subject, content, from_email, to=None, bcc=None, cc=None, attachments=None, email_category:EmailCategory = EmailCategory.GENERAL, fail_silently=True) -> int:
	mail = EmailMessage(
		subject=subject, body=content, from_email=from_email, to=to, bcc=bcc, cc=cc, attachments=attachments
	)
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
	email_record: EmailLog = EmailLog.objects.create(category=email_category, sender=email.from_email, to=', '.join(email.recipients()), subject=email.subject, content=email.body)
	if email.attachments:
		email_attachments = []
		for attachment in email.attachments:
			if isinstance(attachment, MIMEBase):
				email_attachments.append(attachment.get_filename() or '')
		if email_attachments:
			email_record.attachments = ', '.join(email_attachments)
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
	date = now.strftime("%Y-%m-%d")
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


def distinct_qs_value_list(qs: QuerySet, field_name:str) -> Set:
	return set(list(qs.values_list(field_name, flat=True)))
