from NEMO.decorators import customization
from NEMO.views.customization import CustomizationBase


@customization(key="sensors", title="Sensor Data")
class SensorCustomization(CustomizationBase):
	variables = {"sensor_default_daterange": "", "sensor_default_refresh_rate": "0"}
