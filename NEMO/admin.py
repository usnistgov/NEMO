import datetime
import json

from django import forms
from django.contrib import admin, messages
from django.contrib.admin import register
from django.contrib.admin.decorators import display
from django.contrib.admin.models import LogEntry
from django.contrib.admin.widgets import FilteredSelectMultiple
from django.contrib.auth.admin import GroupAdmin
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.admin import GenericStackedInline
from django.db.models import Q
from django.db.models.fields.files import FieldFile
from django.forms import BaseInlineFormSet, ModelMultipleChoiceField
from django.template.defaultfilters import linebreaksbr, urlencode
from django.utils.safestring import mark_safe
from mptt.admin import DraggableMPTTAdmin, MPTTAdminForm, TreeRelatedFieldListFilter

from NEMO.actions import (
    access_requests_export_csv,
    adjustment_requests_export_csv,
    adjustment_requests_mark_as_applied,
    create_next_interlock,
    disable_selected_cards,
    duplicate_configuration,
    duplicate_tool_configuration,
    enable_selected_cards,
    lock_selected_interlocks,
    rebuild_area_tree,
    synchronize_with_tool_usage,
    unlock_selected_interlocks,
    waive_selected_charges,
)
from NEMO.forms import BuddyRequestForm, RecurringConsumableChargeForm, UserPreferencesForm
from NEMO.mixins import ModelAdminRedirectMixin, ObjPermissionAdminMixin
from NEMO.models import (
    Account,
    AccountType,
    ActivityHistory,
    AdjustmentRequest,
    Alert,
    AlertCategory,
    Area,
    AreaAccessRecord,
    BadgeReader,
    BuddyRequest,
    Chemical,
    ChemicalHazard,
    Closure,
    ClosureTime,
    Comment,
    Configuration,
    ConfigurationHistory,
    ConfigurationOption,
    Consumable,
    ConsumableCategory,
    ConsumableWithdraw,
    ContactInformation,
    ContactInformationCategory,
    Customization,
    Door,
    EmailLog,
    Interlock,
    InterlockCard,
    InterlockCardCategory,
    LandingPageChoice,
    MembershipHistory,
    News,
    Notification,
    OnboardingPhase,
    PhysicalAccessLevel,
    PhysicalAccessLog,
    Project,
    ProjectDiscipline,
    ProjectDocuments,
    RecurringConsumableCharge,
    RequestMessage,
    Reservation,
    ReservationQuestions,
    Resource,
    ResourceCategory,
    SafetyCategory,
    SafetyIssue,
    SafetyItem,
    SafetyItemDocuments,
    SafetyTraining,
    ScheduledOutage,
    ScheduledOutageCategory,
    StaffAbsence,
    StaffAbsenceType,
    StaffAvailability,
    StaffAvailabilityCategory,
    StaffCharge,
    StaffKnowledgeBaseCategory,
    StaffKnowledgeBaseItem,
    StaffKnowledgeBaseItemDocuments,
    Task,
    TaskCategory,
    TaskHistory,
    TaskImages,
    TaskStatus,
    TemporaryPhysicalAccess,
    TemporaryPhysicalAccessRequest,
    Tool,
    ToolCredentials,
    ToolDocuments,
    ToolQualificationGroup,
    ToolUsageCounter,
    ToolWaitList,
    TrainingSession,
    UsageEvent,
    User,
    UserDocuments,
    UserKnowledgeBaseCategory,
    UserKnowledgeBaseItem,
    UserKnowledgeBaseItemDocuments,
    UserPreferences,
    UserType,
    record_active_state,
    record_local_many_to_many_changes,
    record_remote_many_to_many_changes_and_save,
)
from NEMO.utilities import admin_get_item, format_daterange
from NEMO.views.customization import ProjectsAccountsCustomization
from NEMO.widgets.dynamic_form import (
    DynamicForm,
    PostUsageFloatFieldQuestion,
    PostUsageNumberFieldQuestion,
    admin_render_dynamic_form_preview,
    validate_dynamic_form_model,
)


# Formset to require at least one inline form
class AtLeastOneRequiredInlineFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        if not any(cleaned_data and not cleaned_data.get("DELETE", False) for cleaned_data in self.cleaned_data):
            raise forms.ValidationError("A minimum of one item is required.")


class DocumentModelAdmin(admin.TabularInline):
    extra = 1


class ToolAdminForm(forms.ModelForm):
    class Meta:
        model = Tool
        fields = "__all__"

    class Media:
        js = ("admin/tool/tool.js", "admin/dynamic_form_preview/dynamic_form_preview.js")
        css = {"": ("admin/dynamic_form_preview/dynamic_form_preview.css",)}

    qualified_users = forms.ModelMultipleChoiceField(
        queryset=User.objects.all(),
        required=False,
        widget=FilteredSelectMultiple(verbose_name="Users", is_stacked=False),
    )

    required_resources = forms.ModelMultipleChoiceField(
        queryset=Resource.objects.all(),
        required=False,
        widget=FilteredSelectMultiple(verbose_name="Required resources", is_stacked=False),
    )

    nonrequired_resources = forms.ModelMultipleChoiceField(
        queryset=Resource.objects.all(),
        required=False,
        widget=FilteredSelectMultiple(verbose_name="Nonrequired resources", is_stacked=False),
    )

    _tool_calendar_color = forms.CharField(
        required=False, max_length=9, initial="#33ad33", widget=forms.TextInput(attrs={"type": "color"})
    )

    def __init__(self, *args, **kwargs):
        super(ToolAdminForm, self).__init__(*args, **kwargs)
        # Limit interlock selection to ones not already linked (make sure to include current one)
        if "_interlock" in self.fields:
            self.fields["_interlock"].queryset = Interlock.objects.filter(
                Q(id=self.instance._interlock_id) | Q(tool__isnull=True, door__isnull=True)
            )
        if self.instance.pk:
            self.fields["qualified_users"].initial = self.instance.user_set.all()
            self.fields["required_resources"].initial = self.instance.required_resource_set.all()
            self.fields["nonrequired_resources"].initial = self.instance.nonrequired_resource_set.all()

    def clean__pre_usage_questions(self):
        questions = self.cleaned_data["_pre_usage_questions"]
        try:
            return json.dumps(json.loads(questions), indent=4)
        except:
            pass
        return questions

    def clean__post_usage_questions(self):
        questions = self.cleaned_data["_post_usage_questions"]
        try:
            return json.dumps(json.loads(questions), indent=4)
        except:
            pass
        return questions

    def clean(self):
        cleaned_data = super().clean()
        image = cleaned_data.get("_image")

        # only resize if an image is present and has changed
        if image and not isinstance(image, FieldFile):
            from NEMO.utilities import resize_image

            # resize image to 500x500 maximum
            cleaned_data["_image"] = resize_image(image, 500)

        return cleaned_data


class ToolDocumentsInline(DocumentModelAdmin):
    model = ToolDocuments


@register(Tool)
class ToolAdmin(admin.ModelAdmin):
    inlines = [ToolDocumentsInline]
    list_display = (
        "name_display",
        "_category",
        "visible",
        "operational_display",
        "_operation_mode",
        "problematic",
        "is_configurable",
        "has_pre_usage_questions",
        "has_post_usage_questions",
        "id",
    )
    filter_horizontal = ("_backup_owners", "_superusers", "_adjustment_request_reviewers")
    search_fields = ("name", "_description", "_serial")
    list_filter = (
        "visible",
        "_operational",
        "_operation_mode",
        "_category",
        "_location",
        ("_requires_area_access", admin.RelatedOnlyFieldListFilter),
    )
    readonly_fields = ("_post_usage_preview", "_pre_usage_preview")
    autocomplete_fields = [
        "_primary_owner",
        "parent_tool",
        "_grant_physical_access_level_upon_qualification",
    ]
    actions = [duplicate_tool_configuration]
    form = ToolAdminForm
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "name",
                    "parent_tool",
                    "_category",
                    "_operation_mode",
                    "qualified_users",
                    "_qualifications_never_expire",
                    "_pre_usage_questions",
                    "_pre_usage_preview",
                    "_post_usage_questions",
                    "_post_usage_preview",
                )
            },
        ),
        ("Additional Information", {"fields": ("_description", "_serial", "_image", "_tool_calendar_color")}),
        ("Current state", {"fields": ("visible", "_operational")}),
        (
            "Contact information",
            {
                "fields": (
                    "_primary_owner",
                    "_backup_owners",
                    "_superusers",
                    "_notification_email_address",
                    "_location",
                    "_phone_number",
                )
            },
        ),
        ("Approval", {"fields": ("_adjustment_request_reviewers",)}),
        ("Reservation", {"fields": ("_reservation_horizon", "_missed_reservation_threshold")}),
        (
            "Usage policy",
            {
                "fields": (
                    "_policy_off_between_times",
                    "_policy_off_start_time",
                    "_policy_off_end_time",
                    "_policy_off_weekend",
                    "_minimum_usage_block_time",
                    "_maximum_usage_block_time",
                    "_maximum_reservations_per_day",
                    "_minimum_time_between_reservations",
                    "_maximum_future_reservation_time",
                )
            },
        ),
        (
            "Area Access",
            {
                "fields": (
                    "_requires_area_access",
                    "_grant_physical_access_level_upon_qualification",
                    "_grant_badge_reader_access_upon_qualification",
                    "_interlock",
                    "_max_delayed_logoff",
                    "_ask_to_leave_area_when_done_using",
                )
            },
        ),
        ("Dependencies", {"fields": ("required_resources", "nonrequired_resources")}),
    )

    @admin.display(description="Pre Questions", ordering="_pre_usage_questions", boolean=True)
    def has_pre_usage_questions(self, obj: Tool):
        return True if obj.pre_usage_questions else False

    @admin.display(description="Post Questions", ordering="_post_usage_questions", boolean=True)
    def has_post_usage_questions(self, obj: Tool):
        return True if obj.post_usage_questions else False

    def _pre_usage_preview(self, obj: Tool):
        return admin_render_dynamic_form_preview(obj.pre_usage_questions, "tool_usage_group_question", obj.id)

    def _post_usage_preview(self, obj: Tool):
        return admin_render_dynamic_form_preview(obj.post_usage_questions, "tool_usage_group_question", obj.id)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """We only want non children tool to be eligible as parents"""
        if db_field.name == "parent_tool":
            kwargs["queryset"] = Tool.objects.filter(parent_tool__isnull=True)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        """
        Explicitly record any project membership changes on non-child tools.
        """
        if not obj.allow_wait_list() and obj.current_wait_list():
            obj.current_wait_list().update(deleted=True)
            messages.warning(
                request,
                f"The wait list for {obj} has been deleted because the current operation mode does not allow it.",
            )

        if obj.parent_tool:
            super(ToolAdmin, self).save_model(request, obj, form, change)
        else:
            record_remote_many_to_many_changes_and_save(
                request, obj, form, change, "qualified_users", super(ToolAdmin, self).save_model
            )
            if "required_resources" in form.changed_data:
                obj.required_resource_set.set(form.cleaned_data["required_resources"])
            if "nonrequired_resources" in form.changed_data:
                obj.nonrequired_resource_set.set(form.cleaned_data["nonrequired_resources"])


@register(ToolWaitList)
class ToolWaitList(admin.ModelAdmin):
    list_display = ["tool", "user", "date_entered", "date_exited", "expired", "deleted"]
    list_filter = ["deleted", "expired", "tool"]


@register(ToolQualificationGroup)
class ToolQualificationGroup(admin.ModelAdmin):
    list_display = ["name", "get_tools"]
    filter_horizontal = ["tools"]

    @admin.display(description="Tools", ordering="tools")
    def get_tools(self, obj: ToolQualificationGroup):
        return mark_safe("<br>".join([str(tool) for tool in obj.tools.all()]))


class AreaAdminForm(MPTTAdminForm):
    class Meta:
        model = Area
        fields = "__all__"

    area_calendar_color = forms.CharField(
        required=False, max_length=9, initial="#88B7CD", widget=forms.TextInput(attrs={"type": "color"})
    )


@register(Area)
class AreaAdmin(DraggableMPTTAdmin):
    list_display = (
        "tree_actions",
        "indented_title",
        "name",
        "parent_area",
        "category",
        "requires_reservation",
        "maximum_capacity",
        "reservation_warning",
        "buddy_system_allowed",
        "id",
    )
    filter_horizontal = ["adjustment_request_reviewers", "access_request_reviewers"]
    fieldsets = (
        (None, {"fields": ("name", "parent_area", "category", "reservation_email", "abuse_email")}),
        ("Additional Information", {"fields": ("area_calendar_color",)}),
        (
            "Area access",
            {
                "fields": (
                    "requires_reservation",
                    "logout_grace_period",
                    "auto_logout_time",
                    "buddy_system_allowed",
                )
            },
        ),
        (
            "Occupancy",
            {
                "fields": (
                    "maximum_capacity",
                    "count_staff_in_occupancy",
                    "count_service_personnel_in_occupancy",
                    "reservation_warning",
                )
            },
        ),
        ("Approval", {"fields": ("adjustment_request_reviewers", "access_request_reviewers")}),
        ("Reservation", {"fields": ("reservation_horizon", "missed_reservation_threshold")}),
        (
            "Policy",
            {
                "fields": (
                    "policy_off_between_times",
                    "policy_off_start_time",
                    "policy_off_end_time",
                    "policy_off_weekend",
                    "minimum_usage_block_time",
                    "maximum_usage_block_time",
                    "maximum_reservations_per_day",
                    "minimum_time_between_reservations",
                    "maximum_future_reservation_time",
                )
            },
        ),
    )
    list_display_links = ("indented_title",)
    list_filter = ("requires_reservation", ("parent_area", TreeRelatedFieldListFilter))
    search_fields = ("name",)
    actions = [rebuild_area_tree]

    mptt_level_indent = 20
    form = AreaAdminForm

    def get_fieldsets(self, request, obj: Area = None):
        """
        Remove some fieldsets if this area is a parent
        """
        if obj and not obj.is_leaf_node():
            return [i for i in self.fieldsets if i[0] not in ["Area access", "Reservation", "Policy"]]
        return super().get_fieldsets(request, obj)

    def save_model(self, request, obj: Area, form, change):
        parent_area: Area = obj.parent_area
        if parent_area:
            # if this area has a parent, that parent needs to be cleaned and updated
            parent_area.is_now_a_parent()
        super(AreaAdmin, self).save_model(request, obj, form, change)


@register(TrainingSession)
class TrainingSessionAdmin(ObjPermissionAdminMixin, ModelAdminRedirectMixin, admin.ModelAdmin):
    list_display = (
        "id",
        "trainer",
        "trainee",
        "tool",
        "project",
        "type",
        "date",
        "duration",
        "qualified",
        "usage_event",
    )
    list_filter = (
        "qualified",
        "date",
        "type",
        ("tool", admin.RelatedOnlyFieldListFilter),
        ("project", admin.RelatedOnlyFieldListFilter),
        ("trainer", admin.RelatedOnlyFieldListFilter),
        ("trainee", admin.RelatedOnlyFieldListFilter),
    )
    date_hierarchy = "date"
    autocomplete_fields = ["trainer", "trainee", "tool", "project", "validated_by", "waived_by"]
    actions = [waive_selected_charges]

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """We only want staff user and tool superusers to be possible trainers"""
        if db_field.name == "trainer":
            kwargs["queryset"] = User.objects.filter(Q(is_staff=True) | Q(superuser_for_tools__isnull=False)).distinct()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@register(StaffCharge)
class StaffChargeAdmin(ObjPermissionAdminMixin, ModelAdminRedirectMixin, admin.ModelAdmin):
    list_display = ("id", "staff_member", "customer", "start", "end")
    list_filter = (
        "start",
        ("customer", admin.RelatedOnlyFieldListFilter),
        ("staff_member", admin.RelatedOnlyFieldListFilter),
    )
    date_hierarchy = "start"
    autocomplete_fields = ["staff_member", "customer", "project", "validated_by", "waived_by"]
    actions = [waive_selected_charges]


@register(AreaAccessRecord)
class AreaAccessRecordAdmin(ObjPermissionAdminMixin, ModelAdminRedirectMixin, admin.ModelAdmin):
    list_display = ("id", "customer", "area", "project", "start", "end")
    list_filter = (("area", TreeRelatedFieldListFilter), "start")
    date_hierarchy = "start"
    autocomplete_fields = ["customer", "project", "validated_by", "waived_by"]
    actions = [waive_selected_charges]


@register(Configuration)
class ConfigurationAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "tool",
        "is_tool_visible",
        "name",
        "enabled",
        "qualified_users_are_maintainers",
        "display_order",
        "exclude_from_configuration_agenda",
    )
    list_filter = ["enabled", ("tool", admin.RelatedOnlyFieldListFilter), "tool__visible"]
    filter_horizontal = ("maintainers",)
    actions = [duplicate_configuration]
    autocomplete_fields = ["tool"]

    @admin.display(ordering="tool__visible", boolean=True, description="Tool visible")
    def is_tool_visible(self, obj: Configuration):
        return obj.tool.visible


@register(ConfigurationHistory)
class ConfigurationHistoryAdmin(admin.ModelAdmin):
    list_display = ("id", "configuration", "user", "modification_time", "slot")
    date_hierarchy = "modification_time"
    autocomplete_fields = ["user"]


@register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ("name", "id", "active", "type", "start_date")
    search_fields = ("name",)
    list_filter = ("active", ("type", admin.RelatedOnlyFieldListFilter), "start_date")

    def save_model(self, request, obj, form, change):
        """Audit account and project active status."""
        super(AccountAdmin, self).save_model(request, obj, form, change)
        record_active_state(request, obj, form, "active", not change)


class ProjectAdminForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = "__all__"

    members = forms.ModelMultipleChoiceField(
        queryset=User.objects.all(),
        required=False,
        widget=FilteredSelectMultiple(verbose_name="Users", is_stacked=False),
    )

    principal_investigators = forms.ModelMultipleChoiceField(
        queryset=User.objects.all(),
        required=False,
        widget=FilteredSelectMultiple(verbose_name="Principal investigators", is_stacked=False),
    )

    def __init__(self, *args, **kwargs):
        super(ProjectAdminForm, self).__init__(*args, **kwargs)
        if "application_identifier" in self.fields:
            self.fields["application_identifier"].label = ProjectsAccountsCustomization.get(
                "project_application_identifier_name"
            )
        if self.instance.pk:
            self.fields["members"].initial = self.instance.user_set.all()
            self.fields["principal_investigators"].initial = self.instance.manager_set.all()


class ProjectDocumentsInline(DocumentModelAdmin):
    model = ProjectDocuments


@register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("name", "id", "get_application_identifier", "account", "active", "get_managers", "start_date")
    filter_horizontal = ("only_allow_tools",)
    search_fields = ("name", "application_identifier", "account__name")
    list_filter = (
        "active",
        ("account", admin.RelatedOnlyFieldListFilter),
        "start_date",
        ("manager_set", admin.RelatedOnlyFieldListFilter),
    )
    inlines = [ProjectDocumentsInline]
    form = ProjectAdminForm
    autocomplete_fields = ["account"]

    @display(ordering="application_identifier")
    def get_application_identifier(self, project: Project):
        return project.application_identifier

    @display(description="PIs", ordering="manager_set")
    def get_managers(self, project: Project):
        return mark_safe("<br>".join([pi.get_name() for pi in project.manager_set.all()]))

    def save_model(self, request, obj, form, change):
        """
        Audit project creation and modification. Also save any project membership changes explicitly.
        """
        record_remote_many_to_many_changes_and_save(
            request, obj, form, change, "members", super(ProjectAdmin, self).save_model
        )
        # Make a history entry if a project has been moved under an account.
        # This applies to newly created projects and project ownership reassignment.
        if "account" in form.changed_data:
            # Create a membership removal entry for the project if it used to belong to another account:
            if change:
                previous_account = MembershipHistory()
                previous_account.authorizer = request.user
                previous_account.child_content_object = obj
                previous_account.parent_content_object = Account.objects.get(pk=form.initial["account"])
                previous_account.action = MembershipHistory.Action.REMOVED
                previous_account.save()

            # Create a membership addition entry for the project with its current account.
            current_account = MembershipHistory()
            current_account.authorizer = request.user
            current_account.child_content_object = obj
            current_account.parent_content_object = obj.account
            current_account.action = MembershipHistory.Action.ADDED
            current_account.save()

        # Record whether the project is active or not.
        record_active_state(request, obj, form, "active", not change)

        if "principal_investigators" in form.changed_data:
            obj.manager_set.set(form.cleaned_data["principal_investigators"])


class ConfigurationOptionInline(admin.TabularInline):
    model = ConfigurationOption
    extra = 0


@register(Reservation)
class ReservationAdmin(ObjPermissionAdminMixin, ModelAdminRedirectMixin, admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "creator",
        "tool",
        "area",
        "project",
        "start",
        "end",
        "duration",
        "cancelled",
        "missed",
        "shortened",
    )
    readonly_fields = ("descendant",)
    list_filter = (
        "cancelled",
        "missed",
        ("tool", admin.RelatedOnlyFieldListFilter),
        ("area", TreeRelatedFieldListFilter),
        ("user", admin.RelatedOnlyFieldListFilter),
    )
    date_hierarchy = "start"
    inlines = [ConfigurationOptionInline]
    autocomplete_fields = ["user", "creator", "tool", "project", "cancelled_by", "validated_by", "waived_by"]
    actions = [waive_selected_charges]


class ReservationQuestionsForm(forms.ModelForm):
    class Meta:
        model = ReservationQuestions
        fields = "__all__"

    class Media:
        js = ("admin/dynamic_form_preview/dynamic_form_preview.js",)
        css = {"": ("admin/dynamic_form_preview/dynamic_form_preview.css",)}

    def clean_questions(self):
        questions = self.cleaned_data["questions"]
        try:
            return json.dumps(json.loads(questions), indent=4)
        except:
            pass
        return questions

    def clean(self):
        cleaned_data = super().clean()
        reservation_questions = cleaned_data.get("questions")
        tool_reservations = cleaned_data.get("tool_reservations")
        only_tools = cleaned_data.get("only_for_tools")
        area_reservations = cleaned_data.get("area_reservations")
        only_areas = cleaned_data.get("only_for_areas")
        if not tool_reservations and not area_reservations:
            self.add_error("tool_reservations", "Reservation questions have to apply to tool and/or area reservations")
            self.add_error("area_reservations", "Reservation questions have to apply to tool and/or area reservations")
        if not tool_reservations and only_tools:
            self.add_error(
                "tool_reservations", "You cannot restrict tools these questions apply to without enabling it for tools"
            )
        if not area_reservations and only_areas:
            self.add_error(
                "area_reservations", "You cannot restrict areas these questions apply to without enabling it for areas"
            )
        # Validate reservation_questions JSON format
        if reservation_questions:
            errors = validate_dynamic_form_model(reservation_questions, "reservation_group_question", self.instance.id)
            for error in errors:
                self.add_error("questions", error)
        return cleaned_data


@register(ReservationQuestions)
class ReservationQuestionsAdmin(admin.ModelAdmin):
    form = ReservationQuestionsForm
    filter_horizontal = ("only_for_tools", "only_for_areas", "only_for_projects")
    readonly_fields = ("questions_preview",)
    list_filter = ["enabled", "tool_reservations", "area_reservations"]
    list_display = ["name", "enabled", "tool_reservations", "area_reservations"]
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "enabled",
                    "name",
                    "questions",
                    "questions_preview",
                    "tool_reservations",
                    "only_for_tools",
                    "area_reservations",
                    "only_for_areas",
                    "only_for_projects",
                )
            },
        ),
    )

    def questions_preview(self, obj):
        return admin_render_dynamic_form_preview(obj.questions, "reservation_group_question", obj.id)


@register(UsageEvent)
class UsageEventAdmin(ObjPermissionAdminMixin, ModelAdminRedirectMixin, admin.ModelAdmin):
    list_display = ("id", "tool", "user", "operator", "project", "start", "end", "duration", "remote_work")
    list_filter = ("remote_work", "training", "start", "end", ("tool", admin.RelatedOnlyFieldListFilter))
    date_hierarchy = "start"
    autocomplete_fields = ["tool", "user", "operator", "project", "validated_by", "waived_by"]
    actions = [waive_selected_charges]


@register(Consumable)
class ConsumableAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "quantity",
        "category",
        "visible",
        "reusable",
        "allow_self_checkout",
        "reminder_threshold",
        "reminder_email",
        "id",
    )
    list_filter = ("visible", ("category", admin.RelatedOnlyFieldListFilter), "reusable", "allow_self_checkout")
    filter_horizontal = ["self_checkout_only_users"]
    search_fields = ("name",)
    readonly_fields = ("reminder_threshold_reached",)


@register(ConsumableCategory)
class ConsumableCategoryAdmin(admin.ModelAdmin):
    list_display = ("name",)


@register(ConsumableWithdraw)
class ConsumableWithdrawAdmin(ObjPermissionAdminMixin, ModelAdminRedirectMixin, admin.ModelAdmin):
    list_display = ("id", "customer", "merchant", "consumable", "quantity", "project", "date")
    list_filter = ("date", ("consumable", admin.RelatedOnlyFieldListFilter))
    date_hierarchy = "date"
    autocomplete_fields = ["customer", "merchant", "consumable", "project", "validated_by", "waived_by"]
    actions = [waive_selected_charges]


@register(RecurringConsumableCharge)
class RecurringConsumableChargeAdmin(admin.ModelAdmin):
    form = RecurringConsumableChargeForm
    list_display = ("name", "customer", "project", "get_recurrence_display", "last_charge", "next_charge")
    list_filter = (("customer", admin.RelatedOnlyFieldListFilter),)
    readonly_fields = ("last_charge", "last_updated", "last_updated_by")
    autocomplete_fields = ["customer", "consumable", "project"]

    def save_model(self, request, obj: RecurringConsumableCharge, form, change):
        obj.save_with_user(request.user)


class InterlockCardAdminForm(forms.ModelForm):
    class Meta:
        model = InterlockCard
        widgets = {"password": forms.PasswordInput(render_value=True)}
        fields = "__all__"

    def clean_extra_args(self):
        extra_args = self.cleaned_data["extra_args"]
        try:
            return json.dumps(json.loads(extra_args), indent=4)
        except:
            pass
        return extra_args

    def clean(self):
        if any(self.errors):
            return
        cleaned_data = super().clean()
        category = cleaned_data["category"]
        from NEMO import interlocks

        interlocks.get(category, False).clean_interlock_card(self)
        return cleaned_data


@register(InterlockCard)
class InterlockCardAdmin(admin.ModelAdmin):
    search_fields = ["name", "server"]
    form = InterlockCardAdminForm
    list_display = ("name", "enabled", "server", "port", "number", "category", "even_port", "odd_port")
    actions = [disable_selected_cards, enable_selected_cards]


class InterlockAdminForm(forms.ModelForm):
    class Meta:
        model = Interlock
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if hasattr(self.instance, "card"):
            from NEMO import interlocks

            category = self.instance.card.category
            if "channel" in self.fields:
                self.fields["channel"].label = interlocks.get(category, False).channel_name
            if "unit_id" in self.fields:
                self.fields["unit_id"].label = interlocks.get(category, False).unit_id_name

    def clean(self):
        if any(self.errors):
            return
        cleaned_data = super().clean()
        from NEMO import interlocks

        category = self.cleaned_data["card"].category
        interlocks.get(category, False).clean_interlock(self)
        return cleaned_data


@register(Interlock)
class InterlockAdmin(admin.ModelAdmin):
    search_fields = ["name", "card__name", "card__server"]
    form = InterlockAdminForm
    list_display = (
        "id",
        "name",
        "get_card_enabled",
        "card",
        "channel",
        "unit_id",
        "state",
        "tool",
        "door",
        "most_recent_reply_time",
    )
    list_filter = (
        "card__enabled",
        ("card", admin.RelatedOnlyFieldListFilter),
        "state",
        ("tool", admin.RelatedOnlyFieldListFilter),
        ("door", admin.RelatedOnlyFieldListFilter),
    )
    actions = [lock_selected_interlocks, unlock_selected_interlocks, synchronize_with_tool_usage, create_next_interlock]
    readonly_fields = ["state", "most_recent_reply", "most_recent_reply_time"]
    autocomplete_fields = ["card"]

    @display(boolean=True, ordering="card__enabled", description="Card Enabled")
    def get_card_enabled(self, obj):
        return obj.card.enabled


@register(InterlockCardCategory)
class InterlockCardCategoryAdmin(admin.ModelAdmin):
    list_display = ("name",)


@register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "urgency",
        "tool",
        "creator",
        "creation_time",
        "last_updated",
        "problem_category",
        "cancelled",
        "resolved",
        "resolution_category",
    )
    list_filter = (
        "urgency",
        "resolved",
        "cancelled",
        "safety_hazard",
        "creation_time",
        ("tool", admin.RelatedOnlyFieldListFilter),
        ("creator", admin.RelatedOnlyFieldListFilter),
    )
    date_hierarchy = "creation_time"
    autocomplete_fields = ["tool", "creator", "last_updated_by", "resolver"]


@register(TaskCategory)
class TaskCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "stage")


@register(TaskStatus)
class TaskStatusAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "notify_primary_tool_owner",
        "notify_backup_tool_owners",
        "notify_tool_notification_email",
        "custom_notification_email_address",
    )


@register(TaskHistory)
class TaskHistoryAdmin(admin.ModelAdmin):
    list_display = ("id", "task", "status", "time", "user")
    readonly_fields = ("time",)
    date_hierarchy = "time"
    autocomplete_fields = ["user"]


@register(TaskImages)
class TaskImagesAdmin(admin.ModelAdmin):
    list_display = ("id", "get_tool", "task", "uploaded_at")

    @admin.display(ordering="tool", description="Tool Name")
    def get_tool(self, task_image: TaskImages):
        return task_image.task.tool.name


@register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "tool",
        "author",
        "creation_date",
        "expiration_date",
        "visible",
        "staff_only",
        "hidden_by",
        "hide_date",
    )
    list_filter = ("visible", "creation_date", ("tool", admin.RelatedOnlyFieldListFilter), "staff_only")
    date_hierarchy = "creation_date"
    search_fields = ("content",)
    autocomplete_fields = ["author", "tool", "hidden_by"]


@register(Resource)
class ResourceAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "available")
    list_filter = ("available", "category")
    filter_horizontal = ("fully_dependent_tools", "partially_dependent_tools", "dependent_areas")


@register(ActivityHistory)
class ActivityHistoryAdmin(admin.ModelAdmin):
    list_display = ("__str__", "get_item", "action", "date", "authorizer")
    list_filter = (
        "action",
        ("content_type", admin.RelatedOnlyFieldListFilter),
    )
    date_hierarchy = "date"

    @admin.display(description="Item")
    def get_item(self, obj: ActivityHistory):
        return admin_get_item(obj.content_type, obj.object_id)


@register(MembershipHistory)
class MembershipHistoryAdmin(admin.ModelAdmin):
    list_display = (
        "__str__",
        "get_parent",
        "action",
        "get_child",
        "date",
        "authorizer",
    )
    list_filter = (
        ("parent_content_type", admin.RelatedOnlyFieldListFilter),
        ("child_content_type", admin.RelatedOnlyFieldListFilter),
    )
    date_hierarchy = "date"
    autocomplete_fields = ["authorizer"]

    @admin.display(description="Parent")
    def get_parent(self, obj: MembershipHistory):
        return admin_get_item(obj.parent_content_type, obj.parent_object_id)

    @admin.display(description="Child")
    def get_child(self, obj: MembershipHistory):
        return admin_get_item(obj.child_content_type, obj.child_object_id)


@register(UserType)
class UserTypeAdmin(admin.ModelAdmin):
    list_display = ("name",)


@register(UserPreferences)
class UserPreferencesAdmin(admin.ModelAdmin):
    list_display = ("user",)
    search_fields = [
        "user__first_name",
        "user__last_name",
        "user__username",
    ]
    filter_horizontal = ["tool_freed_time_notifications", "tool_task_notifications"]
    form = UserPreferencesForm


class UserAdminForm(forms.ModelForm):
    class Meta:
        model = User
        fields = "__all__"

    tool_qualifications = forms.ModelMultipleChoiceField(
        label="Qualifications",
        queryset=Tool.objects.filter(parent_tool__isnull=True),
        required=False,
        widget=FilteredSelectMultiple(verbose_name="tools", is_stacked=False),
    )

    backup_owner_on_tools = forms.ModelMultipleChoiceField(
        queryset=Tool.objects.filter(parent_tool__isnull=True),
        required=False,
        widget=FilteredSelectMultiple(verbose_name="tools", is_stacked=False),
    )

    superuser_on_tools = forms.ModelMultipleChoiceField(
        queryset=Tool.objects.filter(parent_tool__isnull=True),
        required=False,
        widget=FilteredSelectMultiple(verbose_name="tools", is_stacked=False),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["tool_qualifications"].initial = self.instance.qualifications.all()
            self.fields["backup_owner_on_tools"].initial = self.instance.backup_for_tools.all()
            self.fields["superuser_on_tools"].initial = self.instance.superuser_for_tools.all()


class UserDocumentsInline(DocumentModelAdmin):
    model = UserDocuments


@register(User)
class UserAdmin(admin.ModelAdmin):
    form = UserAdminForm
    inlines = [UserDocumentsInline]
    filter_horizontal = (
        "groups",
        "user_permissions",
        "projects",
        "managed_projects",
        "physical_access_levels",
        "onboarding_phases",
        "safety_trainings",
    )
    fieldsets = (
        (
            "Personal information",
            {"fields": ("first_name", "last_name", "username", "email", "badge_number", "type", "domain", "notes")},
        ),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_user_office",
                    "is_accounting_officer",
                    "is_service_personnel",
                    "is_technician",
                    "is_facility_manager",
                    "is_superuser",
                    "training_required",
                    "groups",
                    "user_permissions",
                    "physical_access_levels",
                )
            },
        ),
        ("Important dates", {"fields": ("date_joined", "last_login", "access_expiration")}),
        (
            "Facility information",
            {
                "fields": (
                    "tool_qualifications",
                    "backup_owner_on_tools",
                    "superuser_on_tools",
                    "projects",
                    "managed_projects",
                )
            },
        ),
        (
            "Other information",
            {
                "fields": (
                    "onboarding_phases",
                    "safety_trainings",
                )
            },
        ),
    )
    search_fields = ("first_name", "last_name", "username", "email")
    list_display = (
        "username",
        "first_name",
        "last_name",
        "email",
        "is_active",
        "access_expiration",
        "domain",
        "is_staff",
        "is_user_office",
        "is_accounting_officer",
        "is_technician",
        "is_service_personnel",
        "is_facility_manager",
        "is_superuser",
        "date_joined",
        "last_login",
    )
    list_filter = (
        "is_active",
        "access_expiration",
        "domain",
        "is_staff",
        "is_user_office",
        "is_accounting_officer",
        "is_facility_manager",
        "is_superuser",
        "is_technician",
        "is_service_personnel",
        "date_joined",
        "last_login",
    )

    def save_model(self, request, obj, form, change):
        """Audit project membership and qualifications when a user is saved."""
        super(UserAdmin, self).save_model(request, obj, form, change)
        record_local_many_to_many_changes(request, obj, form, "projects")
        record_local_many_to_many_changes(request, obj, form, "qualifications", "tool_qualifications")
        record_local_many_to_many_changes(request, obj, form, "physical_access_levels")
        record_active_state(request, obj, form, "is_active", not change)
        if "tool_qualifications" in form.changed_data:
            obj.qualifications.set(form.cleaned_data["tool_qualifications"])
        if "backup_owner_on_tools" in form.changed_data:
            obj.backup_for_tools.set(form.cleaned_data["backup_owner_on_tools"])
        if "superuser_on_tools" in form.changed_data:
            obj.superuser_for_tools.set(form.cleaned_data["superuser_on_tools"])


@register(PhysicalAccessLog)
class PhysicalAccessLogAdmin(admin.ModelAdmin):
    list_display = ("user", "door", "time", "result")
    list_filter = (("door", admin.RelatedOnlyFieldListFilter), "result")
    search_fields = ("user__first_name", "user__last_name", "user__username", "door__name")
    date_hierarchy = "time"

    def has_delete_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@register(SafetyIssue)
class SafetyIssueAdmin(admin.ModelAdmin):
    list_display = ("id", "reporter", "creation_time", "visible", "resolved", "resolution_time", "resolver")
    list_filter = (
        "resolved",
        "visible",
        "creation_time",
        "resolution_time",
        ("reporter", admin.RelatedOnlyFieldListFilter),
    )
    readonly_fields = ("creation_time", "resolution_time")
    search_fields = ("location", "concern", "progress", "resolution")
    autocomplete_fields = ["reporter", "resolver"]


@register(SafetyCategory)
class SafetyCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "display_order")


class SafetyItemDocumentsInline(DocumentModelAdmin):
    model = SafetyItemDocuments


@register(SafetyItem)
class SafetyItemAdmin(admin.ModelAdmin):
    inlines = [SafetyItemDocumentsInline]
    list_display = ("name", "category", "get_documents_number")
    list_filter = (("category", admin.RelatedOnlyFieldListFilter),)

    @display(description="Documents")
    def get_documents_number(self, obj: SafetyItem):
        return SafetyItemDocuments.objects.filter(safety_item=obj).count()


@register(StaffKnowledgeBaseCategory)
class StaffKnowledgeBaseCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "display_order")


class StaffKnowledgeBaseItemDocumentsInline(DocumentModelAdmin):
    model = StaffKnowledgeBaseItemDocuments


@register(StaffKnowledgeBaseItem)
class StaffKnowledgeBaseItemAdmin(admin.ModelAdmin):
    inlines = [StaffKnowledgeBaseItemDocumentsInline]
    list_display = ("name", "category", "get_documents_number")
    list_filter = (("category", admin.RelatedOnlyFieldListFilter),)

    @display(description="Documents")
    def get_documents_number(self, obj: StaffKnowledgeBaseItem):
        return StaffKnowledgeBaseItemDocuments.objects.filter(item=obj).count()


@register(UserKnowledgeBaseCategory)
class UserKnowledgeBaseCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "display_order")


class UserKnowledgeBaseItemDocumentsInline(DocumentModelAdmin):
    model = UserKnowledgeBaseItemDocuments


@register(UserKnowledgeBaseItem)
class UserKnowledgeBaseItemAdmin(admin.ModelAdmin):
    inlines = [UserKnowledgeBaseItemDocumentsInline]
    list_display = ("name", "category", "get_documents_number")
    list_filter = (("category", admin.RelatedOnlyFieldListFilter),)

    @display(description="Documents")
    def get_documents_number(self, obj: UserKnowledgeBaseItem):
        return UserKnowledgeBaseItemDocuments.objects.filter(item=obj).count()


class DoorAdminForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super(DoorAdminForm, self).__init__(*args, **kwargs)
        # Limit interlock selection to ones not already linked (and exclude current one)
        if "interlock" in self.fields:
            self.fields["interlock"].queryset = Interlock.objects.filter(
                Q(id=self.instance.interlock_id) | Q(tool__isnull=True, door__isnull=True)
            )


@register(Door)
class DoorAdmin(admin.ModelAdmin):
    list_display = ("name", "get_areas", "interlock", "get_absolute_url", "id")
    form = DoorAdminForm
    filter_horizontal = ["areas"]

    @display(description="Areas", ordering="areas")
    def get_areas(self, door: Door):
        return mark_safe("<br>".join([area.name for area in door.areas.order_by("name")]))


@register(AlertCategory)
class AlertCategoryAdmin(admin.ModelAdmin):
    list_display = ("name",)


class AlertAdminForm(forms.ModelForm):
    contents = forms.CharField(widget=forms.Textarea(attrs={"rows": 3, "cols": 50}))

    class Meta:
        model = Alert
        fields = "__all__"


@register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "category",
        "creation_time",
        "creator",
        "debut_time",
        "expiration_time",
        "user",
        "dismissible",
        "expired",
        "deleted",
    )
    list_filter = ("category", "dismissible", "expired", "deleted")
    date_hierarchy = "creation_time"
    form = AlertAdminForm


class PhysicalAccessLevelForm(forms.ModelForm):
    class Meta:
        model = PhysicalAccessLevel
        fields = "__all__"

    class Media:
        js = ("admin/physical_access_level/access_level.js",)

    authorized_users = forms.ModelMultipleChoiceField(
        queryset=User.objects.all(),
        required=False,
        widget=FilteredSelectMultiple(verbose_name="Users", is_stacked=False),
    )

    closures = forms.ModelMultipleChoiceField(
        queryset=Closure.objects.all(),
        required=False,
        widget=FilteredSelectMultiple(verbose_name="Closures", is_stacked=False),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["authorized_users"].initial = self.instance.user_set.all()
            self.fields["closures"].initial = self.instance.closure_set.all()

    def clean(self):
        cleaned_data = super().clean()
        schedule = cleaned_data.get("schedule")
        if schedule == PhysicalAccessLevel.Schedule.WEEKDAYS:
            start_date = cleaned_data.get("weekdays_start_time")
            end_date = cleaned_data.get("weekdays_end_time")
            if not start_date:
                self.add_error("weekdays_start_time", "Start time is required for weekdays.")
            if not end_date:
                self.add_error("weekdays_end_time", "End time is required for weekdays.")
        else:
            cleaned_data["weekdays_start_time"] = None
            cleaned_data["weekdays_end_time"] = None
        return cleaned_data


@register(PhysicalAccessLevel)
class PhysicalAccessLevelAdmin(admin.ModelAdmin):
    search_fields = ["name", "area__name"]
    form = PhysicalAccessLevelForm
    list_display = ("name", "area", "get_schedule_display_with_times", "allow_staff_access", "allow_user_request")
    list_filter = (("area", TreeRelatedFieldListFilter), "allow_staff_access", "allow_user_request")

    def save_model(self, request, obj, form, change):
        """
        Explicitly record any membership changes.
        """
        record_remote_many_to_many_changes_and_save(request, obj, form, change, "authorized_users", super().save_model)
        if "closures" in form.changed_data:
            obj.closure_set.set(form.cleaned_data["closures"])


class ClosureTimeInline(admin.TabularInline):
    model = ClosureTime
    formset = AtLeastOneRequiredInlineFormSet
    min_num = 1
    extra = 1


class ClosureAdminForm(forms.ModelForm):
    def clean(self):
        if any(self.errors):
            return
        cleaned_data = super().clean()
        alert_template = cleaned_data.get("alert_template")
        alert_days_before = cleaned_data.get("alert_days_before")
        if alert_days_before is not None and not alert_template:
            self.add_error("alert_template", "Please provide an alert message")
        if alert_template:
            if alert_days_before is None:
                self.add_error("alert_days_before", "Please select when the alert should be displayed")
            try:
                validate_closure = Closure()
                validate_closure.name = cleaned_data.get("name")
                validate_closure.alert_template = alert_template
                validate_closure.staff_absent = cleaned_data.get("staff_absent")
                access_levels = cleaned_data.get("physical_access_levels")
                closure_time = ClosureTime()
                closure_time.closure = validate_closure
                closure_time.start_time = datetime.datetime.now()
                closure_time.end_time = datetime.datetime.now()
                closure_time.alert_contents(access_levels=access_levels)
            except Exception as template_exception:
                self.add_error("alert_template", str(template_exception))

    class Meta:
        model = Closure
        fields = "__all__"

    class Media:
        js = ("admin/time_options_override.js",)


@register(Closure)
class ClosureAdmin(admin.ModelAdmin):
    inlines = [ClosureTimeInline]
    form = ClosureAdminForm
    list_display = ("name", "alert_days_before", "get_times_display", "staff_absent", "notify_managers_last_occurrence")
    filter_horizontal = ("physical_access_levels",)
    list_filter = (
        ("physical_access_levels__area", TreeRelatedFieldListFilter),
        "staff_absent",
        "notify_managers_last_occurrence",
    )
    readonly_fields = ("alert_preview",)
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "name",
                    "alert_days_before",
                    "alert_template",
                    "alert_preview",
                    "notify_managers_last_occurrence",
                    "staff_absent",
                    "physical_access_levels",
                )
            },
        ),
    )

    def alert_preview(self, obj: Closure):
        if obj.alert_template and obj.closuretime_set.exists():
            try:
                alert_style = "width: 350px; color: #a94442; background-color: #f2dede; border-color: #dca7a7;padding: 15px; margin-bottom: 10px; border: 1px solid transparent; border-radius: 4px;"
                display_title = f'<span style="font-weight:bold">{obj.name}</span><br>' if obj.name else ""
                return iframe_content(
                    f'<div style="{alert_style}">{display_title}{linebreaksbr(obj.closuretime_set.first().alert_contents())}</div>',
                    extra_style="padding-bottom: 15%",
                )
            except Exception:
                pass
        return ""

    @admin.display(description="Times")
    def get_times_display(self, closure: Closure) -> str:
        return mark_safe(
            "<br>".join(
                [
                    format_daterange(
                        ct.start_time,
                        ct.end_time,
                        dt_format="SHORT_DATETIME_FORMAT",
                        d_format="SHORT_DATE_FORMAT",
                        date_separator=" ",
                        time_separator=" - ",
                    )
                    for ct in ClosureTime.objects.filter(closure=closure)
                ]
            )
        )


class TemporaryPhysicalAccessAdminForm(forms.ModelForm):
    class Meta:
        model = TemporaryPhysicalAccess
        fields = "__all__"

    class Media:
        js = ("admin/time_options_override.js",)


@register(TemporaryPhysicalAccess)
class TemporaryPhysicalAccessAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "start_time", "end_time", "get_area_name", "get_schedule_display_with_times")
    list_filter = (
        ("physical_access_level", admin.RelatedOnlyFieldListFilter),
        ("physical_access_level__area", TreeRelatedFieldListFilter),
        "end_time",
        "start_time",
        ("user", admin.RelatedOnlyFieldListFilter),
    )
    form = TemporaryPhysicalAccessAdminForm
    autocomplete_fields = ["user", "physical_access_level"]

    @admin.display(ordering="physical_access_level__area", description="Area")
    def get_area_name(self, tpa: TemporaryPhysicalAccess) -> str:
        return tpa.physical_access_level.area.name

    @admin.display(description="Schedule")
    def get_schedule_display_with_times(self, tpa: TemporaryPhysicalAccess) -> str:
        return tpa.physical_access_level.get_schedule_display_with_times()


class TemporaryPhysicalAccessRequestFormAdmin(forms.ModelForm):
    class Meta:
        model = TemporaryPhysicalAccessRequest
        fields = "__all__"


@register(TemporaryPhysicalAccessRequest)
class TemporaryPhysicalAccessRequestAdmin(admin.ModelAdmin):
    form = TemporaryPhysicalAccessRequestFormAdmin
    list_display = (
        "creator",
        "creation_time",
        "other_users_display",
        "start_time",
        "end_time",
        "physical_access_level",
        "status_display",
        "reviewer",
        "deleted",
    )
    list_filter = (
        "status",
        "deleted",
        ("creator", admin.RelatedOnlyFieldListFilter),
        ("physical_access_level", admin.RelatedOnlyFieldListFilter),
    )
    filter_horizontal = ("other_users",)
    actions = [access_requests_export_csv]
    autocomplete_fields = ["creator", "last_updated_by", "reviewer", "physical_access_level"]

    @admin.display(ordering="other_users", description="Buddies")
    def other_users_display(self, access_request: TemporaryPhysicalAccessRequest):
        return mark_safe("<br>".join([u.username for u in access_request.other_users.all()]))

    @admin.display(ordering="status", description="Status")
    def status_display(self, access_request: TemporaryPhysicalAccessRequest):
        return access_request.get_status_display()


@register(ContactInformationCategory)
class ContactInformationCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "display_order")


@register(ContactInformation)
class ContactInformationAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "user")
    autocomplete_fields = ["user"]


@register(LandingPageChoice)
class LandingPageChoiceAdmin(admin.ModelAdmin):
    list_display = (
        "display_order",
        "name",
        "url",
        "open_in_new_tab",
        "secure_referral",
        "hide_from_mobile_devices",
        "hide_from_desktop_computers",
    )
    list_display_links = ("name",)


@register(Customization)
class CustomizationAdmin(admin.ModelAdmin):
    list_display = ("name", "value")
    search_fields = ["name"]


@register(ScheduledOutageCategory)
class ScheduledOutageCategoryAdmin(admin.ModelAdmin):
    list_display = ("name",)


@register(ScheduledOutage)
class ScheduledOutageAdmin(admin.ModelAdmin):
    list_display = ("id", "tool", "area", "resource", "creator", "title", "start", "end")
    list_filter = (
        ("tool", admin.RelatedOnlyFieldListFilter),
        ("area", TreeRelatedFieldListFilter),
        ("resource", admin.RelatedOnlyFieldListFilter),
        ("creator", admin.RelatedOnlyFieldListFilter),
    )
    autocomplete_fields = ["tool", "creator"]


@register(News)
class NewsAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "created", "last_updated", "archived", "pinned")
    list_filter = ("archived", "pinned")


@register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "get_item", "notification_type", "expiration")
    list_filter = (
        ("content_type", admin.RelatedOnlyFieldListFilter),
        "notification_type",
    )
    autocomplete_fields = ["user"]

    @admin.display(description="Item")
    def get_item(self, obj: Notification):
        return admin_get_item(obj.content_type, obj.object_id)


@register(BadgeReader)
class BadgeReaderAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "send_key", "record_key")


class ToolUsageCounterAdminForm(forms.ModelForm):
    class Meta:
        model = ToolUsageCounter
        fields = "__all__"

    def clean(self):
        cleaned_data = super().clean()
        tool = cleaned_data.get("tool")
        tool_usage_question_name = cleaned_data.get("tool_usage_question")
        if tool and tool_usage_question_name:
            error = None
            if tool.post_usage_questions or tool.pre_usage_questions:
                candidate_questions = []
                if tool.post_usage_questions:
                    usage_form = DynamicForm(tool.post_usage_questions)
                    candidate_questions.extend(
                        usage_form.filter_questions(
                            lambda x: isinstance(x, (PostUsageNumberFieldQuestion, PostUsageFloatFieldQuestion))
                        )
                    )
                if tool.pre_usage_questions:
                    usage_form = DynamicForm(tool.pre_usage_questions)
                    candidate_questions.extend(
                        usage_form.filter_questions(
                            lambda x: isinstance(x, (PostUsageNumberFieldQuestion, PostUsageFloatFieldQuestion))
                        )
                    )
                matching_tool_question = any(
                    question for question in candidate_questions if question.name == tool_usage_question_name
                )
                if not matching_tool_question:
                    candidates = {question.name for question in candidate_questions}
                    error = "The tool has no pre/post usage question of type Number or Float with this name."
                    if candidates:
                        error += f" Valid question names are: {', '.join(candidates)}"
            else:
                error = "The tool does not have any pre/post usage questions."
            if error:
                self.add_error("tool_usage_question", error)
        return cleaned_data


@register(ToolUsageCounter)
class ToolUsageCounterAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "tool",
        "tool_usage_question",
        "value",
        "warning_threshold",
        "default_value",
        "staff_members_can_reset",
        "qualified_users_can_reset",
        "superusers_can_reset",
        "last_reset",
        "last_reset_by",
        "is_active",
    )
    list_filter = (
        "staff_members_can_reset",
        "qualified_users_can_reset",
        "superusers_can_reset",
        ("tool", admin.RelatedOnlyFieldListFilter),
        "last_reset",
    )
    readonly_fields = ("warning_threshold_reached",)
    form = ToolUsageCounterAdminForm
    autocomplete_fields = ["tool", "last_reset_by"]


class RequestMessageInlines(GenericStackedInline):
    model = RequestMessage
    extra = 1
    autocomplete_fields = ["author"]


@register(BuddyRequest)
class BuddyRequestAdmin(admin.ModelAdmin):
    inlines = [RequestMessageInlines]
    form = BuddyRequestForm
    list_display = ("user", "start", "end", "area", "reply_count", "expired", "deleted")
    list_filter = (
        "expired",
        "deleted",
        ("user", admin.RelatedOnlyFieldListFilter),
        ("area", TreeRelatedFieldListFilter),
    )
    autocomplete_fields = ["user"]

    @admin.display(ordering="replies", description="Replies")
    def reply_count(self, buddy_request: BuddyRequest):
        return buddy_request.replies.count()


@register(AdjustmentRequest)
class AdjustmentRequestAdmin(admin.ModelAdmin):
    inlines = [RequestMessageInlines]
    list_display = (
        "creator",
        "last_updated",
        "get_item",
        "get_time_difference",
        "get_status_display",
        "reply_count",
        "applied",
        "deleted",
    )
    list_filter = (
        "status",
        "deleted",
        "applied",
        ("creator", admin.RelatedOnlyFieldListFilter),
        ("reviewer", admin.RelatedOnlyFieldListFilter),
    )
    date_hierarchy = "last_updated"
    actions = [adjustment_requests_export_csv, adjustment_requests_mark_as_applied]
    readonly_fields = ["creation_time"]

    @admin.display(description="Diff")
    def get_time_difference(self, adjustment_request: AdjustmentRequest):
        return adjustment_request.get_time_difference()

    @admin.display(ordering="replies", description="Replies")
    def reply_count(self, adjustment_request: AdjustmentRequest):
        return adjustment_request.replies.count()

    @admin.display(description="Item")
    def get_item(self, adjustment_request: AdjustmentRequest):
        return admin_get_item(adjustment_request.item_type, adjustment_request.item_id)

    def delete_queryset(self, request, queryset):
        for obj in queryset:
            obj.delete()


@register(StaffAbsenceType)
class StaffAbsenceTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "description")


@register(StaffAvailabilityCategory)
class StaffAvailabilityCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "display_order")


@register(StaffAvailability)
class StaffAvailabilityAdmin(admin.ModelAdmin):
    search_fields = (
        "staff_member__first_name",
        "staff_member__last_name",
        "staff_member__username",
        "staff_member__email",
    )
    list_display = ("staff_member", "category", "visible", "start_time", "end_time", *StaffAvailability.DAYS)
    list_filter = ("category", *StaffAvailability.DAYS)
    autocomplete_fields = ["staff_member"]

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """We only want active users here"""
        if db_field.name == "staff_member":
            kwargs["queryset"] = User.objects.filter(is_active=True)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@register(StaffAbsence)
class StaffAbsenceAdmin(admin.ModelAdmin):
    list_display = ("creation_time", "staff_member", "absence_type", "full_day", "start_date", "end_date")
    list_filter = (
        ("staff_member", admin.RelatedOnlyFieldListFilter),
        "absence_type",
        "start_date",
        "end_date",
        "creation_time",
    )
    autocomplete_fields = ["staff_member"]


class ChemicalHazardAdminForm(forms.ModelForm):
    class Meta:
        model = ChemicalHazard
        fields = "__all__"

    chemicals = forms.ModelMultipleChoiceField(
        queryset=Chemical.objects.all(),
        required=False,
        widget=FilteredSelectMultiple(verbose_name="Chemicals", is_stacked=False),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["chemicals"].initial = self.instance.chemical_set.all()

    def clean(self):
        cleaned_data = super().clean()
        logo = cleaned_data.get("logo")

        # only resize if a logo is present and has changed
        if logo and not isinstance(logo, FieldFile):
            from NEMO.utilities import resize_image

            # resize image to 250x250 maximum
            cleaned_data["logo"] = resize_image(logo, 250)


@register(ChemicalHazard)
class ChemicalHazardAdmin(admin.ModelAdmin):
    form = ChemicalHazardAdminForm
    list_display = ("name", "display_order")

    def save_model(self, request, obj: ChemicalHazard, form, change):
        super().save_model(request, obj, form, change)
        if "chemicals" in form.changed_data:
            obj.chemical_set.set(form.cleaned_data["chemicals"])


@register(Chemical)
class ChemicalAdmin(admin.ModelAdmin):
    filter_horizontal = ("hazards",)
    list_filter = ("hazards",)


@register(SafetyTraining)
class SafetyTrainingAdmin(admin.ModelAdmin):
    list_display = ("name", "display_order")


@register(OnboardingPhase)
class OnboardingPhaseAdmin(admin.ModelAdmin):
    list_display = ("name", "display_order")


class ToolCredentialsAdminForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["authorized_staff"].queryset = User.objects.filter(is_staff=True)


@register(ToolCredentials)
class ToolCredentialsAdmin(ModelAdminRedirectMixin, admin.ModelAdmin):
    list_display = ["get_tool_category", "tool", "is_tool_visible", "username", "comments"]
    list_filter = [("tool", admin.RelatedOnlyFieldListFilter), "tool__visible"]
    autocomplete_fields = ["tool"]
    filter_horizontal = ["authorized_staff"]
    form = ToolCredentialsAdminForm

    @display(ordering="tool___category", description="Tool category")
    def get_tool_category(self, obj: ToolCredentials) -> str:
        return obj.tool._category

    @admin.display(ordering="tool__visible", boolean=True, description="Tool visible")
    def is_tool_visible(self, obj: Configuration):
        return obj.tool.visible


@register(EmailLog)
class EmailLogAdmin(admin.ModelAdmin):
    list_display = ["id", "category", "sender", "to", "subject", "when", "ok"]
    list_filter = ["category", "ok"]
    search_fields = ["subject", "content", "to"]
    readonly_fields = (
        "when",
        "content_preview",
    )
    date_hierarchy = "when"

    def content_preview(self, obj):
        if obj.content:
            return iframe_content(obj.content)
        else:
            return ""

    def has_delete_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class CustomGroupAdminForm(forms.ModelForm):
    users = ModelMultipleChoiceField(
        queryset=User.objects.all(),
        required=False,
        widget=FilteredSelectMultiple(verbose_name="Users", is_stacked=False),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["users"].initial = self.instance.user_set.all()

    def _save_m2m(self):
        super()._save_m2m()
        exclude = self._meta.exclude
        fields = self._meta.fields
        # Check for fields and exclude
        if fields and "users" not in fields or exclude and "users" in exclude:
            return
        if "users" in self.cleaned_data:
            self.instance.user_set.set(self.cleaned_data["users"])


class CustomGroupAdmin(GroupAdmin):
    form = CustomGroupAdminForm


class PermissionAdminForm(forms.ModelForm):
    users = ModelMultipleChoiceField(
        queryset=User.objects.all(),
        required=False,
        widget=FilteredSelectMultiple(verbose_name="Users", is_stacked=False),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["users"].initial = self.instance.user_set.all()

    def _save_m2m(self):
        super()._save_m2m()
        exclude = self._meta.exclude
        fields = self._meta.fields
        # Check for fields and exclude
        if fields and "users" not in fields or exclude and "users" in exclude:
            return
        if "users" in self.cleaned_data:
            self.instance.user_set.set(self.cleaned_data["users"])


@admin.register(Permission)
class PermissionAdmin(admin.ModelAdmin):
    search_fields = ("name", "codename")
    form = PermissionAdminForm


@admin.register(LogEntry)
class LogEntryAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "action_time", "content_type", "object_id", "object_repr", "action_flag")
    list_filter = [("user", admin.RelatedOnlyFieldListFilter), "action_flag"]

    def __init__(self, model, admin_site):
        model._meta.verbose_name_plural = "Detailed admin history"
        super().__init__(model, admin_site)

    def has_delete_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


def iframe_content(content, extra_style="padding-bottom: 65%") -> str:
    return mark_safe(
        f'<div id="iframe-container" style="position: relative; display: block; overflow: hidden; width:100%; height:100%; {extra_style}"><iframe style="width:100%; height:100%; border:none" src="data:text/html,{urlencode(content)}"></iframe></div><script>django.jQuery("#iframe-container").parent(".readonly").css("flex","1");</script>'
    )


def has_admin_site_permission(request):
    """
    Return True if the given HttpRequest has permission to view
    *at least one* page in the admin site.
    In our case, anyone with a staff permission should be able
    to access the admin site
    """
    user: User = request.user
    return user.is_active and (user.is_superuser or user.get_all_permissions())


# Register our new admin permission
admin.site.has_permission = has_admin_site_permission

# Register other models
admin.site.register(ProjectDiscipline)
admin.site.register(AccountType)
admin.site.register(ResourceCategory)
admin.site.unregister(Group)
admin.site.register(Group, CustomGroupAdmin)
