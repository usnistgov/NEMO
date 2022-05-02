from copy import deepcopy

from django import forms
from django.contrib import admin, messages
from django.contrib.admin import register
from django.contrib.admin.decorators import display
from django.urls import reverse
from django.utils.safestring import mark_safe

from NEMO.apps.sensors.models import Sensor, SensorCard, SensorCardCategory, SensorCategory, SensorData


def duplicate_sensor_configuration(model_admin, request, queryset):
	for sensor in queryset:
		original_name = sensor.name
		new_name = "Copy of " + sensor.name
		try:
			existing_sensor = Sensor.objects.filter(name=new_name)
			if existing_sensor.exists():
				messages.error(
					request,
					mark_safe(
						f'There is already a copy of {original_name} as <a href="{reverse("admin:sensors_sensor_change", args=[existing_sensor.first().id])}">{new_name}</a>. Change the copy\'s name and try again'
					),
				)
				continue
			else:
				new_sensor = deepcopy(sensor)
				new_sensor.name = new_name
				new_sensor.id = None
				new_sensor.pk = None
				new_sensor.save()
				messages.success(
					request,
					mark_safe(
						f'A duplicate of {original_name} has been made as <a href="{reverse("admin:sensors_sensor_change", args=[new_sensor.id])}">{new_sensor.name}</a>'
					),
				)
		except Exception as error:
			messages.error(
				request, f"{original_name} could not be duplicated because of the following error: {str(error)}"
			)


def read_selected_sensors(model_admin, request, queryset):
	for sensor in queryset:
		try:
			response = sensor.read_data(raise_exception=True)
			if isinstance(response, SensorData):
				messages.success(request, f"{sensor} data read: {response.value}")
			elif isinstance(response, str):
				messages.warning(request, response)
		except Exception as error:
			messages.error(request, f"{sensor} data could not be read due to the following error: {str(error)}")


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


class SensorCategoryAdminForm(forms.ModelForm):
	class Meta:
		model = SensorCategory
		fields = "__all__"

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		if self.instance.pk:
			children_ids = [child.id for child in self.instance.all_children()]
			self.fields["parent"].queryset = SensorCategory.objects.exclude(id__in=[self.instance.pk, *children_ids])


@register(SensorCategory)
class SensorCategoryAdmin(admin.ModelAdmin):
	form = SensorCategoryAdminForm
	list_display = ("name", "get_parent", "get_children")

	@display(ordering="children", description="Children")
	def get_children(self, category: SensorCategory) -> str:
		return mark_safe(
			", ".join(
				[
					f'<a href="{reverse("admin:sensors_sensorcategory_change", args=[child.id])}">{child.name}</a>'
					for child in category.children.all()
				]
			)
		)

	@display(ordering="parent", description="Parent")
	def get_parent(self, category: SensorCategory) -> str:
		if not category.parent:
			return ""
		return mark_safe(
			f'<a href="{reverse("admin:sensors_sensorcategory_change", args=[category.parent.id])}">{category.parent.name}</a>'
		)

	def formfield_for_foreignkey(self, db_field, request, **kwargs):
		""" Filter list of potential parents """
		if db_field.name == "parent":
			kwargs["queryset"] = SensorCategory.objects.filter()
		return super().formfield_for_foreignkey(db_field, request, **kwargs)


@register(Sensor)
class SensorAdmin(admin.ModelAdmin):
	form = SensorAdminForm
	list_display = (
		"id",
		"name",
		"visible",
		"card",
		"get_card_enabled",
		"sensor_category",
		"unit_id",
		"read_address",
		"number_of_values",
		"read_frequency",
		"get_last_read",
		"get_last_read_at",
	)
	actions = [duplicate_sensor_configuration, read_selected_sensors]

	@display(boolean=True, ordering="sensor_card__enabled", description="Card Enabled")
	def get_card_enabled(self, obj: Sensor):
		return obj.card.enabled

	@display(description="Last read")
	def get_last_read(self, obj: Sensor):
		last_data_point = obj.last_data_point()
		return last_data_point.value if last_data_point else ""

	@display(description="Last read at")
	def get_last_read_at(self, obj: Sensor):
		last_data_point = obj.last_data_point()
		return last_data_point.created_date if last_data_point else ""


@register(SensorCardCategory)
class SensorCardCategoryAdmin(admin.ModelAdmin):
	list_display = ("name",)


@register(SensorData)
class SensorDataAdmin(admin.ModelAdmin):
	list_display = ("created_date", "sensor", "value", "get_display_value")
	date_hierarchy = "created_date"
	list_filter = ("sensor", "sensor__sensor_category")

	@display(ordering="sensor__data_prefix", description="Display value")
	def get_display_value(self, obj: SensorData):
		return obj.display_value()