from django import forms
from django.contrib import admin, messages
from django.contrib.admin import register
from django.contrib.admin.decorators import display

from NEMO.apps.sensors.models import Sensor, SensorCard, SensorCardCategory, SensorCategory, SensorData


def read_selected_sensors(model_admin, request, queryset):
	for sensor in queryset:
		try:
			sensor.read_data(raise_exception=True)
			messages.success(request, f"Read command has been sent to {sensor}")
		except Exception as error:
			messages.error(request, f"Command could not be sent to {sensor} due to the following error: {str(error)}")


class SensorCardAdminForm(forms.ModelForm):
	class Meta:
		model = SensorCard
		widgets = {"password": forms.PasswordInput(render_value=True)}
		fields = "__all__"

	def clean(self):
		if any(self.errors):
			return
		cleaned_data = super().clean()
		category = cleaned_data["category"]
		from NEMO.apps.sensors import sensors

		sensors.get(category).clean_sensor_card(self)
		return cleaned_data


@register(SensorCard)
class SensorCardAdmin(admin.ModelAdmin):
	form = SensorCardAdminForm
	list_display = ("name", "enabled", "server", "port", "number", "category", "even_port", "odd_port")


class SensorAdminForm(forms.ModelForm):
	class Meta:
		model = Sensor
		fields = "__all__"

	def clean(self):
		if any(self.errors):
			return
		cleaned_data = super().clean()

		card = (
			self.cleaned_data["sensor_card"]
			if "sensor_card" in self.cleaned_data
			else self.cleaned_data["interlock_card"]
		)
		if card:
			category = card.category
			from NEMO.apps.sensors import sensors

			sensors.get(category).clean_sensor(self)
		return cleaned_data


@register(SensorCategory)
class SensorCategoryAdmin(admin.ModelAdmin):
	list_display = ("name",)


@register(Sensor)
class SensorAdmin(admin.ModelAdmin):
	form = SensorAdminForm
	list_display = (
		"id",
		"name",
		"card",
		"get_card_enabled",
		"sensor_category",
		"unit_id",
		"read_address",
		"number_of_values",
		"read_frequency",
		"get_last_read",
	)
	actions = [read_selected_sensors]

	@display(boolean=True, ordering="sensor_card__enabled", description="Card Enabled")
	def get_card_enabled(self, obj: Sensor):
		return obj.card.enabled

	@display(description="Last read")
	def get_last_read(self, obj: Sensor):
		last_data_point = obj.last_data_point()
		return last_data_point.value if last_data_point else ""


@register(SensorCardCategory)
class SensorCardCategoryAdmin(admin.ModelAdmin):
	list_display = ("name",)


@register(SensorData)
class SensorDataAdmin(admin.ModelAdmin):
	list_display = ("created_date", "sensor", "value", "get_display_value")
	date_hierarchy = "created_date"
	list_filter = ("sensor",)

	@display(ordering="sensor__data_prefix", description="Display value")
	def get_display_value(self, obj: SensorData):
		return obj.display_value()
