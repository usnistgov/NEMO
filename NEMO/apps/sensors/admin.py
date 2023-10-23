from copy import deepcopy

from django import forms
from django.contrib import admin, messages
from django.contrib.admin import register
from django.contrib.admin.decorators import display
from django.contrib.admin.utils import display_for_value
from django.urls import reverse
from django.utils.safestring import mark_safe

from NEMO.apps.sensors.models import (
    Sensor,
    SensorAlertEmail,
    SensorAlertLog,
    SensorCard,
    SensorCardCategory,
    SensorCategory,
    SensorData,
)
from NEMO.typing import QuerySetType


def duplicate_sensor_configuration(model_admin, request, queryset: QuerySetType[Sensor]):
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
                new_sensor: Sensor = deepcopy(sensor)
                new_sensor.name = new_name
                new_sensor.read_frequency = 0
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


def read_selected_sensors(model_admin, request, queryset: QuerySetType[Sensor]):
    for sensor in queryset:
        try:
            response = sensor.read_data(raise_exception=True)
            if isinstance(response, SensorData):
                messages.success(request, f"{sensor} data read: {response.value}")
            elif isinstance(response, str):
                messages.warning(request, response)
        except Exception as error:
            messages.error(request, f"{sensor} data could not be read due to the following error: {str(error)}")


@admin.action(description="Hide selected sensors")
def hide_selected_sensors(model_admin, request, queryset: QuerySetType[Sensor]):
    for sensor in queryset:
        sensor.visible = False
        sensor.save(update_fields=["visible"])


@admin.action(description="Show selected sensors")
def show_selected_sensors(model_admin, request, queryset: QuerySetType[Sensor]):
    for sensor in queryset:
        sensor.visible = True
        sensor.save(update_fields=["visible"])


@admin.action(description="Disable selected alerts")
def disable_selected_alerts(model_admin, request, queryset: QuerySetType[SensorAlertEmail]):
    for sensor_alert in queryset:
        sensor_alert.enabled = False
        sensor_alert.save(update_fields=["enabled"])


@admin.action(description="Enable selected alerts")
def enable_selected_alerts(model_admin, request, queryset: QuerySetType[SensorAlertEmail]):
    for sensor_alert in queryset:
        sensor_alert.enabled = True
        sensor_alert.save(update_fields=["enabled"])


@admin.action(description="Disable selected cards")
def disable_selected_cards(model_admin, request, queryset: QuerySetType[SensorCard]):
    for sensor_card in queryset:
        sensor_card.enabled = False
        sensor_card.save(update_fields=["enabled"])


@admin.action(description="Enable selected cards")
def enable_selected_cards(model_admin, request, queryset: QuerySetType[SensorCard]):
    for sensor_card in queryset:
        sensor_card.enabled = True
        sensor_card.save(update_fields=["enabled"])


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
    list_display = ("name", "enabled", "server", "port", "category")
    actions = [disable_selected_cards, enable_selected_cards]


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
        """Filter list of potential parents"""
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
        "get_read_frequency",
        "get_last_read",
        "get_last_read_at",
    )
    list_filter = (
        "visible",
        "sensor_card__enabled",
        ("sensor_card", admin.RelatedOnlyFieldListFilter),
        ("sensor_category", admin.RelatedOnlyFieldListFilter),
    )
    actions = [duplicate_sensor_configuration, read_selected_sensors, hide_selected_sensors, show_selected_sensors]

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

    @display(ordering="read_frequency", description="Read frequency")
    def get_read_frequency(self, obj: Sensor):
        return obj.read_frequency if obj.read_frequency != 0 else display_for_value(False, "", boolean=True)

    def get_deleted_objects(self, objs, request):
        deleted_objects = [str(obj) for obj in objs]
        model_count = {Sensor._meta.verbose_name_plural: len(deleted_objects)}
        perms_needed = []
        protected = []
        return deleted_objects, model_count, perms_needed, protected


@register(SensorCardCategory)
class SensorCardCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "key")


@register(SensorData)
class SensorDataAdmin(admin.ModelAdmin):
    list_display = ("created_date", "sensor", "value", "get_display_value")
    date_hierarchy = "created_date"
    list_filter = (
        ("sensor", admin.RelatedOnlyFieldListFilter),
        ("sensor__sensor_category", admin.RelatedOnlyFieldListFilter),
    )

    @display(ordering="sensor__data_prefix", description="Display value")
    def get_display_value(self, obj: SensorData):
        return obj.display_value()


@register(SensorAlertEmail)
class SensorAlertEmailAdmin(admin.ModelAdmin):
    list_display = ("sensor", "enabled", "trigger_condition", "trigger_no_data", "additional_emails", "triggered_on")
    actions = [disable_selected_alerts, enable_selected_alerts]


@register(SensorAlertLog)
class SensorAlertLogAdmin(admin.ModelAdmin):
    list_display = ["id", "time", "sensor", "reset", "value"]
    list_filter = [("sensor", admin.RelatedOnlyFieldListFilter), "value", "reset"]
    date_hierarchy = "time"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
