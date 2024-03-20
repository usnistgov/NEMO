from django.core.validators import validate_email

from NEMO.decorators import customization
from NEMO.views.customization import CustomizationBase


@customization(key="sensors", title="Sensor data")
class SensorCustomization(CustomizationBase):
    variables = {
        "sensor_default_daterange": "",
        "sensor_default_refresh_rate": "0",
        "sensor_alert_emails": "",
        "sensor_read_retries": "1",
        "sensor_format_millisecond": "",
        "sensor_format_second": "",
        "sensor_format_minute": "",
        "sensor_format_hour": "",
        "sensor_format_day": "",
        "sensor_format_week": "",
        "sensor_format_month": "",
        "sensor_format_quarter": "",
        "sensor_format_year": "",
    }

    def validate(self, name, value):
        if name == "sensor_alert_emails":
            recipients = tuple([e for e in value.split(",") if e])
            for email in recipients:
                validate_email(email)
