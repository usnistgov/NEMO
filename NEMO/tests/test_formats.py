import datetime
import zoneinfo

from django.conf import settings
from django.test import TestCase
from django.utils import timezone
from django.utils.formats import date_format, time_format
from django.utils.timezone import make_aware

from NEMO.utilities import format_daterange, format_datetime


class FormatTestCase(TestCase):
    def test_format_daterange(self):
        self.assertTrue(format_datetime())
        today = datetime.datetime.today()
        self.assertEqual(format_datetime(datetime.datetime.today()), date_format(today, "DATETIME_FORMAT"))
        now = datetime.datetime.now()
        self.assertEqual(format_datetime(now), date_format(today, "DATETIME_FORMAT"))
        now_tz = timezone.now()
        self.assertTrue(format_datetime(now_tz))
        self.assertEqual(format_datetime(now_tz.time()), time_format(now_tz))
        self.assertEqual(format_datetime(now_tz.date()), date_format(now_tz))

        dt_format = "m/d/Y @ g:i A"
        start = datetime.datetime(2022, 2, 11, 5, 0, 0)
        end = start + datetime.timedelta(days=2)
        self.assertEqual(
            format_daterange(start, end, dt_format=dt_format), f"from 02/11/2022 @ 5:00 AM to 02/13/2022 @ 5:00 AM"
        )

        start_same_day = datetime.datetime(2022, 2, 11, 5, 0, 0)
        end_same_day = start_same_day + datetime.timedelta(hours=2)
        self.assertEqual(
            format_daterange(start_same_day, end_same_day, dt_format=dt_format), f"02/11/2022 from 5:00 AM to 7:00 AM"
        )

        start_midnight = datetime.datetime(2022, 2, 11, 0, 0, 0)
        end_midnight = datetime.datetime(2022, 2, 11, 23, 59, 0)
        self.assertEqual(
            format_daterange(start_midnight, end_midnight, dt_format=dt_format), f"02/11/2022 from 12:00 AM to 11:59 PM"
        )

        t_format = "g:i A"
        start_time = datetime.time(8, 0, 0)
        end_time = datetime.time(14, 0, 0)
        self.assertEqual(format_daterange(start_time, end_time, t_format=t_format), f"from 8:00 AM to 2:00 PM")

        d_format = "m/d/Y"
        start_date = datetime.date(2022, 2, 11)
        end_date = datetime.date(2022, 2, 11)
        self.assertEqual(format_daterange(start_date, end_date, d_format=d_format), f"from 02/11/2022 to 02/11/2022")

        tz = zoneinfo.ZoneInfo("US/Pacific")
        self.assertEqual(settings.TIME_ZONE, "US/Eastern")
        start_tz = make_aware(datetime.datetime(2022, 2, 11, 5, 0, 0), tz)  # 5AM Pacific => 8AM Eastern
        end_tz = start_tz + datetime.timedelta(days=2)
        self.assertNotEqual(
            format_daterange(start_tz, end_tz, dt_format=dt_format),
            f"from 02/11/2022 @ 5:00 AM to 02/13/2022 @ 5:00 AM",
        )
        self.assertEqual(
            format_daterange(start_tz, end_tz, dt_format=dt_format),
            f"from 02/11/2022 @ 8:00 AM to 02/13/2022 @ 8:00 AM",
        )

        start_midnight_tz = make_aware(datetime.datetime(2022, 2, 11, 0, 0, 0), tz)  # midnight Pacific -> 3AM Eastern
        end_midnight_tz = make_aware(
            datetime.datetime(2022, 2, 11, 23, 59, 0), tz
        )  # 11:59 PM Pacific -> 2:59AM Eastern
        self.assertEqual(
            format_daterange(start_midnight_tz, end_midnight_tz, dt_format=dt_format),
            f"from 02/11/2022 @ 3:00 AM to 02/12/2022 @ 2:59 AM",
        )
