from datetime import date, datetime, time, timedelta

try:
    import zoneinfo
except ImportError:
    from backports import zoneinfo

from django.conf import settings
from django.test import TestCase
from django.utils import timezone
from django.utils.formats import date_format, time_format
from django.utils.timezone import make_aware

from NEMO.utilities import format_daterange, format_datetime, get_duration_with_off_schedule


class FormatTestCase(TestCase):
    def test_format_daterange(self):
        self.assertTrue(format_datetime())
        today = datetime.today()
        self.assertEqual(format_datetime(datetime.today()), date_format(today, "DATETIME_FORMAT"))
        now = datetime.now()
        self.assertEqual(format_datetime(now), date_format(today, "DATETIME_FORMAT"))
        now_tz = timezone.now()
        self.assertTrue(format_datetime(now_tz))
        self.assertEqual(format_datetime(now_tz.time()), time_format(now_tz))
        self.assertEqual(format_datetime(now_tz.date()), date_format(now_tz))

        dt_format = "m/d/Y @ g:i A"
        start = datetime(2022, 2, 11, 5, 0, 0)
        end = start + timedelta(days=2)
        self.assertEqual(
            format_daterange(start, end, dt_format=dt_format), f"from 02/11/2022 @ 5:00 AM to 02/13/2022 @ 5:00 AM"
        )

        start_same_day = datetime(2022, 2, 11, 5, 0, 0)
        end_same_day = start_same_day + timedelta(hours=2)
        self.assertEqual(
            format_daterange(start_same_day, end_same_day, dt_format=dt_format), f"02/11/2022 from 5:00 AM to 7:00 AM"
        )

        start_midnight = datetime(2022, 2, 11, 0, 0, 0)
        end_midnight = datetime(2022, 2, 11, 23, 59, 0)
        self.assertEqual(
            format_daterange(start_midnight, end_midnight, dt_format=dt_format), f"02/11/2022 from 12:00 AM to 11:59 PM"
        )

        t_format = "g:i A"
        start_time = time(8, 0, 0)
        end_time = time(14, 0, 0)
        self.assertEqual(format_daterange(start_time, end_time, t_format=t_format), f"from 8:00 AM to 2:00 PM")

        d_format = "m/d/Y"
        start_date = date(2022, 2, 11)
        end_date = date(2022, 2, 11)
        self.assertEqual(format_daterange(start_date, end_date, d_format=d_format), f"from 02/11/2022 to 02/11/2022")

        tz = zoneinfo.ZoneInfo("US/Pacific")
        self.assertEqual(settings.TIME_ZONE, "US/Eastern")
        start_tz = make_aware(datetime(2022, 2, 11, 5, 0, 0), tz)  # 5AM Pacific => 8AM Eastern
        end_tz = start_tz + timedelta(days=2)
        self.assertNotEqual(
            format_daterange(start_tz, end_tz, dt_format=dt_format),
            f"from 02/11/2022 @ 5:00 AM to 02/13/2022 @ 5:00 AM",
        )
        self.assertEqual(
            format_daterange(start_tz, end_tz, dt_format=dt_format),
            f"from 02/11/2022 @ 8:00 AM to 02/13/2022 @ 8:00 AM",
        )

        start_midnight_tz = make_aware(datetime(2022, 2, 11, 0, 0, 0), tz)  # midnight Pacific -> 3AM Eastern
        end_midnight_tz = make_aware(datetime(2022, 2, 11, 23, 59, 0), tz)  # 11:59 PM Pacific -> 2:59AM Eastern
        self.assertEqual(
            format_daterange(start_midnight_tz, end_midnight_tz, dt_format=dt_format),
            f"from 02/11/2022 @ 3:00 AM to 02/12/2022 @ 2:59 AM",
        )

    def test_duration_with_off_schedule_weekends(self):
        # 6-10 am local starting on a Tuesday (Sep 17 2024 is a Tuesday)
        start = (
            timezone.now().astimezone().replace(year=2024, month=9, day=17, hour=6, minute=0, second=0, microsecond=0)
        )
        end = start + timedelta(hours=4) + timedelta(days=7)
        duration = end - start

        # no time off
        self.assertEqual(duration, get_duration_with_off_schedule(start, end, False, False, None, None))
        # time off whole weekend
        self.assertEqual(
            duration - timedelta(days=2), get_duration_with_off_schedule(start, end, True, False, None, None)
        )

        # time off overlapping beginning, end on Saturday
        end = start + timedelta(days=4) + timedelta(hours=4)
        duration = end - start
        # only time off will be Saturday from 0am to 10am
        self.assertEqual(
            duration - timedelta(hours=10), get_duration_with_off_schedule(start, end, True, False, None, None)
        )

        # time off overlapping end, start previous Sunday, end on Tuesday
        end = start
        start = start - timedelta(days=2)
        duration = end - start
        # only time off will be Sunday from 6am to midnight
        self.assertEqual(
            duration - timedelta(hours=18), get_duration_with_off_schedule(start, end, True, False, None, None)
        )

    def test_duration_with_off_schedule_weekdays_normal(self):
        # 6-10 am local on a Tuesday (Sep 17 2024 is a Tuesday)
        start = (
            timezone.now().astimezone().replace(year=2024, month=9, day=17, hour=6, minute=0, second=0, microsecond=0)
        )
        end = start + timedelta(hours=4)
        duration = end - start
        # no time off
        self.assertEqual(duration, get_duration_with_off_schedule(start, end, False, False, None, None))
        # time off in the middle
        self.assertEqual(
            duration - timedelta(minutes=45),
            get_duration_with_off_schedule(
                start, end, False, True, time(hour=7, minute=0, second=0), time(hour=7, minute=45, second=0)
            ),
        )
        # time off overlapping beginning
        self.assertEqual(
            duration - timedelta(minutes=15),
            get_duration_with_off_schedule(
                start, end, False, True, time(hour=5, minute=0, second=0), time(hour=6, minute=15, second=0)
            ),
        )
        # time off overlapping end
        self.assertEqual(
            duration - timedelta(minutes=15),
            get_duration_with_off_schedule(
                start, end, False, True, time(hour=9, minute=45, second=0), time(hour=17, minute=15, second=0)
            ),
        )
        # time off before window
        self.assertEqual(
            duration,
            get_duration_with_off_schedule(
                start, end, False, True, time(hour=3, minute=45, second=0), time(hour=5, minute=15, second=0)
            ),
        )
        # time off after window
        self.assertEqual(
            duration,
            get_duration_with_off_schedule(
                start, end, False, True, time(hour=13, minute=45, second=0), time(hour=15, minute=15, second=0)
            ),
        )

        # test with multiple days
        # 6am to 10am the next day
        end = start + timedelta(days=1, hours=4)
        duration = end - start
        # no time off
        self.assertEqual(duration, get_duration_with_off_schedule(start, end, False, False, None, None))
        # time off in the middle
        self.assertEqual(
            duration - timedelta(minutes=90),
            get_duration_with_off_schedule(
                start, end, False, True, time(hour=7, minute=00, second=0), time(hour=7, minute=45, second=0)
            ),
        )
        # time off overlapping beginning (15 first day + 75 second)
        self.assertEqual(
            duration - timedelta(minutes=90),
            get_duration_with_off_schedule(
                start, end, False, True, time(hour=5, minute=0, second=0), time(hour=6, minute=15, second=0)
            ),
        )
        # time off overlapping end (150 + 15 second)
        self.assertEqual(
            duration - timedelta(minutes=165),
            get_duration_with_off_schedule(
                start, end, False, True, time(hour=9, minute=45, second=0), time(hour=12, minute=15, second=0)
            ),
        )

    def test_duration_with_off_schedule_weekdays_reverse(self):
        # 6pm-10 am local on a Tuesday (Sep 17 2024 is a Tuesday)
        start = (
            timezone.now().astimezone().replace(year=2024, month=9, day=17, hour=18, minute=0, second=0, microsecond=0)
        )
        end = start + timedelta(hours=16)
        duration = end - start
        # no time off
        self.assertEqual(duration, get_duration_with_off_schedule(start, end, False, False, None, None))
        # time off in the middle
        self.assertEqual(
            duration - timedelta(hours=4),
            get_duration_with_off_schedule(
                start, end, False, True, time(hour=22, minute=0, second=0), time(hour=2, minute=0, second=0)
            ),
        )
        # time off overlapping beginning
        self.assertEqual(
            duration - timedelta(hours=8),
            get_duration_with_off_schedule(
                start, end, False, True, time(hour=17, minute=0, second=0), time(hour=2, minute=0, second=0)
            ),
        )
        # time off overlapping end
        self.assertEqual(
            duration - timedelta(hours=12),
            get_duration_with_off_schedule(
                start, end, False, True, time(hour=22, minute=00, second=0), time(hour=12, minute=00, second=0)
            ),
        )
        # time off before/after window
        self.assertEqual(
            duration,
            get_duration_with_off_schedule(
                start, end, False, True, time(hour=13, minute=45, second=0), time(hour=15, minute=15, second=0)
            ),
        )

        # test with multiple days
        # 6pm to 10am the following day
        end = start + timedelta(days=1, hours=16)
        duration = end - start
        # no time off
        self.assertEqual(duration, get_duration_with_off_schedule(start, end, False, False, None, None))
        # time off in the middle
        self.assertEqual(
            duration - timedelta(hours=8),
            get_duration_with_off_schedule(
                start, end, False, True, time(hour=22, minute=0, second=0), time(hour=2, minute=0, second=0)
            ),
        )
        # time off overlapping beginning (6 first + 2 + 7 second + 2 third)
        self.assertEqual(
            duration - timedelta(hours=17),
            get_duration_with_off_schedule(
                start, end, False, True, time(hour=17, minute=0, second=0), time(hour=2, minute=0, second=0)
            ),
        )
        # time off overlapping end (2 first + 12 + 2 second + 10 third)
        self.assertEqual(
            duration - timedelta(hours=26),
            get_duration_with_off_schedule(
                start, end, False, True, time(hour=22, minute=00, second=0), time(hour=12, minute=00, second=0)
            ),
        )
