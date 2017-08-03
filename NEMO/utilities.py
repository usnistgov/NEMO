from calendar import monthrange
from datetime import timedelta, datetime

from dateutil import parser
from dateutil.parser import parse
from dateutil.rrule import MONTHLY, rrule
from django.utils import timezone
from django.utils.timezone import localtime


def bootstrap_primary_color(color_type):
	if color_type == 'success':
		return '#5cb85c'
	elif color_type == 'info':
		return '#5bc0de'
	elif color_type == 'warning':
		return '#f0ad4e'
	elif color_type == 'danger':
		return '#d9534f'
	return None


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


def parse_parameter_string(parameter_dictionary, parameter_key, maximum_length=3000, raise_on_error=False, default_return=''):
	"""
	Attempts to parse a string from an HTTP GET or POST dictionary and applies validation checks.
	"""
	try:
		parameter = parameter_dictionary[parameter_key].strip()
		if raise_on_error and len(parameter) > maximum_length:
			raise Exception('The parameter named {} is {} characters long, exceeding the maximum length of {} characters.'.format(parameter_key, len(parameter), maximum_length))
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


def get_month_timeframe(date):
	if date:
		start = parse(date)
	else:
		start = timezone.now()
	first_of_the_month = localize(datetime(start.year, start.month, 1))
	last_of_the_month = localize(datetime(start.year, start.month, monthrange(start.year, start.month)[1], 23, 59, 59, 0))
	return first_of_the_month, last_of_the_month


def extract_times(parameters, input_timezone=None):
	"""
	Extract the "start" and "end" parameters from an HTTP request while performing a few logic validation checks.
	The function assumes the UNIX timestamp is in the local timezone. Use input_timezone to specify the timezone.
	"""
	try:
		start = parameters['start']
	except:
		raise Exception("The request parameters did not contain a start time.")

	try:
		end = parameters['end']
	except:
		raise Exception("The request parameters did not contain an end time.")

	try:
		start = float(start)
		start = datetime.utcfromtimestamp(start)
		start = localize(start, input_timezone)
	except:
		raise Exception("The request parameters did not have a valid start time.")

	try:
		end = float(end)
		end = datetime.utcfromtimestamp(end)
		end = localize(end, input_timezone)
	except:
		raise Exception("The request parameters did not have a valid end time.")

	if end < start:
		raise Exception("The request parameters have an end time that precedes the start time.")

	return start, end


def extract_date(date):
	return localize(datetime.strptime(date, '%Y-%m-%d'))


def extract_dates(parameters):
	"""
	Extract the "start" and "end" parameters from an HTTP request while performing a few logic validation checks.
	"""
	try:
		start = parameters['start']
	except:
		raise Exception("The request parameters did not contain a start time.")

	try:
		end = parameters['end']
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
	return local_time.strftime("%A, %B ") + str(day) + suffix + local_time.strftime(", %Y @ ") + local_time.strftime("%I:%M %p").lstrip('0')


def localize(dt, tz=None):
	tz = tz or timezone.get_current_timezone()
	if isinstance(dt, list):
		return [tz.localize(d) for d in dt]
	else:
		return tz.localize(dt)


def naive_local_current_datetime():
	return localtime(timezone.now()).replace(tzinfo=None)


def beginning_of_the_day(t, in_local_timezone=True):
	""" Returns the BEGINNING of today's day (12:00:00.000000 AM of the current day) in LOCAL time. """
	midnight = t.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
	return localize(midnight) if in_local_timezone else midnight


def end_of_the_day(t, in_local_timezone=True):
	""" Returns the END of today's day (11:59:59.999999 PM of the current day) in LOCAL time. """
	midnight = t.replace(hour=23, minute=59, second=59, microsecond=999999, tzinfo=None)
	return localize(midnight) if in_local_timezone else midnight