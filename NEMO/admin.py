import sys
from json import loads

from django import forms
from django.contrib import admin
from django.contrib.admin import register
from django.contrib.admin.widgets import FilteredSelectMultiple
from django.contrib.auth.models import Permission
from django.db.models import Q
from django.db.models.fields.files import FieldFile
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from mptt.admin import DraggableMPTTAdmin, MPTTAdminForm, TreeRelatedFieldListFilter

from NEMO.actions import (
	lock_selected_interlocks,
	synchronize_with_tool_usage,
	unlock_selected_interlocks,
	duplicate_tool_configuration,
	rebuild_area_tree,
)
from NEMO.forms import BuddyRequestForm
from NEMO.models import (
	Account,
	ActivityHistory,
	Alert,
	Area,
	AreaAccessRecord,
	Comment,
	Configuration,
	ConfigurationHistory,
	Consumable,
	ConsumableCategory,
	ConsumableWithdraw,
	ContactInformation,
	BadgeReader,
	ContactInformationCategory,
	Customization,
	Door,
	Interlock,
	InterlockCard,
	LandingPageChoice,
	MembershipHistory,
	News,
	Notification,
	PhysicalAccessLevel,
	PhysicalAccessLog,
	Project,
	Reservation,
	Resource,
	ResourceCategory,
	SafetyIssue,
	ScheduledOutage,
	ScheduledOutageCategory,
	StaffCharge,
	Task,
	TaskCategory,
	TaskHistory,
	TaskStatus,
	Tool,
	TrainingSession,
	UsageEvent,
	User,
	UserType,
	UserPreferences,
	TaskImages,
	InterlockCardCategory,
	record_remote_many_to_many_changes_and_save,
	record_local_many_to_many_changes,
	record_active_state,
	AlertCategory,
	ToolUsageCounter,
	PhysicalAccessException,
	BuddyRequest,
	EmailLog,
	BuddyRequestMessage,
	ToolDocuments,
	ReservationQuestions,
	AccountType,
)
from NEMO.widgets.dynamic_form import (
	DynamicForm,
	PostUsageNumberFieldQuestion,
	PostUsageFloatFieldQuestion,
	PostUsageGroupQuestion,
)


class ToolAdminForm(forms.ModelForm):
	class Meta:
		model = Tool
		fields = "__all__"

	class Media:
		js = ("admin/tool/tool.js", "admin/questions_preview/questions_preview.js")
		css = {"": ("admin/questions_preview/questions_preview.css",)}

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
		if self.instance.pk:
			self.fields["qualified_users"].initial = self.instance.user_set.all()
			self.fields["required_resources"].initial = self.instance.required_resource_set.all()
			self.fields["nonrequired_resources"].initial = self.instance.nonrequired_resource_set.all()

	def clean(self):
		cleaned_data = super().clean()
		parent_tool = cleaned_data.get("parent_tool")
		category = cleaned_data.get("_category")
		location = cleaned_data.get("_location")
		phone_number = cleaned_data.get("_phone_number")
		primary_owner = cleaned_data.get("_primary_owner")
		image = cleaned_data.get("_image")

		# only resize if an image is present and  has changed
		if image and not isinstance(image, FieldFile):
			from NEMO.utilities import resize_image

			# resize image to 500x500 maximum
			cleaned_data["_image"] = resize_image(image, 500)

		if parent_tool:
			if parent_tool.id == self.instance.id:
				self.add_error("parent_tool", "You cannot select the parent to be the tool itself.")
			# in case of alternate tool, remove everything except parent_tool and name
			data = dict([(k, v) for k, v in self.cleaned_data.items() if k == "parent_tool" or k == "name"])
			# an alternate tool is never visible
			data["visible"] = False
			return data
		else:
			if not category:
				self.add_error("_category", "This field is required.")
			if not location:
				self.add_error("_location", "This field is required.")
			if not phone_number:
				self.add_error("_phone_number", "This field is required.")
			if not primary_owner:
				self.add_error("_primary_owner", "This field is required.")

			post_usage_questions = cleaned_data.get("_post_usage_questions")
			# Validate _post_usage_questions JSON format
			if post_usage_questions:
				try:
					loads(post_usage_questions)
				except ValueError:
					self.add_error("_post_usage_questions", "This field needs to be a valid JSON string")
				try:
					DynamicForm(post_usage_questions, self.instance.id).validate()
				except Exception:
					error_info = sys.exc_info()
					self.add_error("_post_usage_questions", error_info[0].__name__ + ": " + str(error_info[1]))

			policy_off_between_times = cleaned_data.get("_policy_off_between_times")
			policy_off_start_time = cleaned_data.get("_policy_off_start_time")
			policy_off_end_time = cleaned_data.get("_policy_off_end_time")
			if policy_off_between_times and (not policy_off_start_time or not policy_off_end_time):
				if not policy_off_start_time:
					self.add_error("_policy_off_start_time", "Start time must be specified")
				if not policy_off_end_time:
					self.add_error("_policy_off_end_time", "End time must be specified")


class ToolDocumentsInline(admin.TabularInline):
	model = ToolDocuments
	extra = 1


@register(Tool)
class ToolAdmin(admin.ModelAdmin):
	inlines = [ToolDocumentsInline]
	list_display = (
		"name_display",
		"_category",
		"visible",
		"operational_display",
		"problematic",
		"is_configurable",
		"id",
	)
	filter_horizontal = ("_backup_owners", "_superusers")
	search_fields = ("name", "_description", "_serial")
	list_filter = ("visible", "_operational", "_category", "_location")
	readonly_fields = ("_post_usage_preview",)
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
					"qualified_users",
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
					"_allow_delayed_logoff",
				)
			},
		),
		("Dependencies", {"fields": ("required_resources", "nonrequired_resources")}),
	)

	def _post_usage_preview(self, obj):
		if obj.id:
			form_validity_div = '<div id="form_validity"></div>' if obj.post_usage_questions else ""
			return mark_safe(
				'<div class="questions_preview">{}{}</div><div class="help questions_preview_help">Save form to preview post usage questions</div>'.format(
					DynamicForm(obj.post_usage_questions, obj.id).render(), form_validity_div
				)
			)

	def formfield_for_foreignkey(self, db_field, request, **kwargs):
		""" We only want non children tool to be eligible as parents """
		if db_field.name == "parent_tool":
			kwargs["queryset"] = Tool.objects.filter(parent_tool__isnull=True)
		return super().formfield_for_foreignkey(db_field, request, **kwargs)

	def save_model(self, request, obj, form, change):
		"""
		Explicitly record any project membership changes.
		"""
		if obj.parent_tool:
			if obj.pk:
				# if this is an update (from regular to child tool), we want to make sure we are creating a clean version. In case the previous tool had fields that are now irrelevant
				clean_alt_tool = Tool(**form.cleaned_data)
				clean_alt_tool.pk = obj.pk
				obj = clean_alt_tool
			super(ToolAdmin, self).save_model(request, obj, form, change)
		else:
			record_remote_many_to_many_changes_and_save(
				request, obj, form, change, "qualified_users", super(ToolAdmin, self).save_model
			)
			if "required_resources" in form.changed_data:
				obj.required_resource_set.set(form.cleaned_data["required_resources"])
			if "nonrequired_resources" in form.changed_data:
				obj.nonrequired_resource_set.set(form.cleaned_data["nonrequired_resources"])


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
		"id",
	)
	fieldsets = (
		(None, {"fields": ("name", "parent_area", "category", "reservation_email", "abuse_email")}),
		("Additional Information", {"fields": ("area_calendar_color",)}),
		(
			"Area access",
			{"fields": ("requires_reservation", "logout_grace_period", "welcome_message", "buddy_system_allowed")},
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
class TrainingSessionAdmin(admin.ModelAdmin):
	list_display = ("id", "trainer", "trainee", "tool", "project", "type", "date", "duration", "qualified")
	list_filter = ("qualified", "date", "type", "tool")
	date_hierarchy = "date"

	def formfield_for_foreignkey(self, db_field, request, **kwargs):
		""" We only want staff user and tool superusers to be possible trainers """
		if db_field.name == "trainer":
			kwargs["queryset"] = User.objects.filter(Q(is_staff=True) | Q(superuser_for_tools__isnull=False)).distinct()
		return super().formfield_for_foreignkey(db_field, request, **kwargs)


@register(StaffCharge)
class StaffChargeAdmin(admin.ModelAdmin):
	list_display = ("id", "staff_member", "customer", "start", "end")
	list_filter = ("start",)
	date_hierarchy = "start"


@register(AreaAccessRecord)
class AreaAccessRecordAdmin(admin.ModelAdmin):
	list_display = ("id", "customer", "area", "project", "start", "end")
	list_filter = (("area", TreeRelatedFieldListFilter), "start")
	date_hierarchy = "start"


@register(Configuration)
class ConfigurationAdmin(admin.ModelAdmin):
	list_display = (
		"id",
		"tool",
		"name",
		"qualified_users_are_maintainers",
		"display_priority",
		"exclude_from_configuration_agenda",
	)
	filter_horizontal = ("maintainers",)


@register(ConfigurationHistory)
class ConfigurationHistoryAdmin(admin.ModelAdmin):
	list_display = ("id", "configuration", "user", "modification_time", "slot")
	date_hierarchy = "modification_time"


@register(Account)
class AccountAdmin(admin.ModelAdmin):
	list_display = ("name", "id", "active", "type", "start_date")
	search_fields = ("name",)
	list_filter = ("active", "type", "start_date")

	def save_model(self, request, obj, form, change):
		""" Audit account and project active status. """
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
		if self.instance.pk:
			self.fields["members"].initial = self.instance.user_set.all()
			self.fields["principal_investigators"].initial = self.instance.manager_set.all()


@register(Project)
class ProjectAdmin(admin.ModelAdmin):
	fields = (
		"name",
		"application_identifier",
		"account",
		"start_date",
		"allow_consumable_withdrawals",
		"active",
		"members",
		"principal_investigators",
		"only_allow_tools",
	)
	list_display = ("name", "id", "application_identifier", "account", "active", "start_date")
	filter_horizontal = ("only_allow_tools",)
	search_fields = ("name", "application_identifier", "account__name")
	list_filter = ("active", "account", "start_date")
	form = ProjectAdminForm

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


@register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
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
	)
	readonly_fields = ("descendant",)
	list_filter = ("cancelled", "missed", "tool", "area")
	date_hierarchy = "start"


class ReservationQuestionsForm(forms.ModelForm):
	class Meta:
		model = ReservationQuestions
		fields = "__all__"

	class Media:
		js = ("admin/reservation_questions/reservation_questions.js", "admin/questions_preview/questions_preview.js")
		css = {"": ("admin/questions_preview/questions_preview.css",)}

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
			try:
				loads(reservation_questions)
			except ValueError:
				self.add_error("questions", "This field needs to be a valid JSON string")
			try:
				dynamic_form = DynamicForm(reservation_questions)
				if any([isinstance(question, PostUsageGroupQuestion) for question in dynamic_form.questions]):
					self.add_error("questions", "Group question is not allowed for reservation questions")
					return
				dynamic_form.validate()
			except KeyError as e:
				self.add_error("questions", f"{e} property is required")
			except Exception:
				error_info = sys.exc_info()
				self.add_error("questions", error_info[0].__name__ + ": " + str(error_info[1]))


@register(ReservationQuestions)
class ReservationQuestionsAdmin(admin.ModelAdmin):
	form = ReservationQuestionsForm
	filter_horizontal = ("only_for_tools", "only_for_areas", "only_for_projects")
	readonly_fields = ("questions_preview",)
	fieldsets = (
		(
			None,
			{
				"fields": (
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
		form_validity_div = ""
		rendered_form = ""
		try:
			rendered_form = DynamicForm(obj.questions).render()
			if obj.questions:
				form_validity_div = '<div id="form_validity"></div>'
		except:
			pass
		return mark_safe(
			'<div class="questions_preview">{}{}</div><div class="help questions_preview_help">Save form to preview reservation questions</div>'.format(
				rendered_form, form_validity_div
			)
		)


@register(UsageEvent)
class UsageEventAdmin(admin.ModelAdmin):
	list_display = ("id", "tool", "user", "operator", "project", "start", "end", "duration")
	list_filter = ("start", "end", "tool")
	date_hierarchy = "start"


@register(Consumable)
class ConsumableAdmin(admin.ModelAdmin):
	list_display = ("name", "quantity", "category", "visible", "reminder_threshold", "reminder_email", "id")
	list_filter = ("visible", "category")
	readonly_fields = ("reminder_threshold_reached",)


@register(ConsumableCategory)
class ConsumableCategoryAdmin(admin.ModelAdmin):
	list_display = ("name",)


@register(ConsumableWithdraw)
class ConsumableWithdrawAdmin(admin.ModelAdmin):
	list_display = ("id", "customer", "merchant", "consumable", "quantity", "project", "date")
	list_filter = ("date", "consumable")
	date_hierarchy = "date"


class InterlockCardAdminForm(forms.ModelForm):
	class Meta:
		model = InterlockCard
		widgets = {"password": forms.PasswordInput(render_value=True)}
		fields = "__all__"

	def clean(self):
		if any(self.errors):
			return
		super(InterlockCardAdminForm, self).clean()
		category = self.cleaned_data["category"]
		from NEMO import interlocks

		interlocks.get(category, False).clean_interlock_card(self)


@register(InterlockCard)
class InterlockCardAdmin(admin.ModelAdmin):
	form = InterlockCardAdminForm
	list_display = ("name", "server", "port", "number", "category", "even_port", "odd_port")


class InterlockAdminForm(forms.ModelForm):
	class Meta:
		model = Interlock
		fields = "__all__"

	def clean(self):
		if any(self.errors):
			return
		super(InterlockAdminForm, self).clean()
		from NEMO import interlocks

		category = self.cleaned_data["card"].category
		interlocks.get(category, False).clean_interlock(self)


@register(Interlock)
class InterlockAdmin(admin.ModelAdmin):
	form = InterlockAdminForm
	list_display = ("id", "card", "channel", "state", "tool", "door")
	actions = [lock_selected_interlocks, unlock_selected_interlocks, synchronize_with_tool_usage]
	readonly_fields = ["state", "most_recent_reply"]


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
	list_filter = ("urgency", "resolved", "cancelled", "safety_hazard", "creation_time", "tool")
	date_hierarchy = "creation_time"


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


@register(TaskImages)
class TaskImagesAdmin(admin.ModelAdmin):
	list_display = ("id", "get_tool", "task", "uploaded_at")

	def get_tool(self, task_image: TaskImages):
		return task_image.task.tool.name

	get_tool.admin_order_field = "tool"  # Allows column order sorting
	get_tool.short_description = "Tool Name"  # Renames column head


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
	list_filter = ("visible", "creation_date", "tool", "staff_only")
	date_hierarchy = "creation_date"
	search_fields = ("content",)


@register(Resource)
class ResourceAdmin(admin.ModelAdmin):
	list_display = ("name", "category", "available")
	list_filter = ("available", "category")
	filter_horizontal = ("fully_dependent_tools", "partially_dependent_tools", "dependent_areas")


@register(ActivityHistory)
class ActivityHistoryAdmin(admin.ModelAdmin):
	list_display = ("__str__", "content_type", "object_id", "action", "date", "authorizer")
	date_hierarchy = "date"


@register(MembershipHistory)
class MembershipHistoryAdmin(admin.ModelAdmin):
	list_display = (
		"__str__",
		"parent_content_type",
		"parent_object_id",
		"action",
		"child_content_type",
		"child_object_id",
		"date",
		"authorizer",
	)
	date_hierarchy = "date"


@register(UserType)
class UserTypeAdmin(admin.ModelAdmin):
	list_display = ("name",)


@register(UserPreferences)
class UserPreferencesAdmin(admin.ModelAdmin):
	list_display = ("user",)


class UserAdminForm(forms.ModelForm):
	class Meta:
		model = User
		fields = "__all__"

	backup_owner_on_tools = forms.ModelMultipleChoiceField(
		queryset=Tool.objects.all(),
		required=False,
		widget=FilteredSelectMultiple(verbose_name="tools", is_stacked=False),
	)

	superuser_on_tools = forms.ModelMultipleChoiceField(
		queryset=Tool.objects.all(),
		required=False,
		widget=FilteredSelectMultiple(verbose_name="tools", is_stacked=False),
	)

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		if self.instance.pk:
			self.fields["backup_owner_on_tools"].initial = self.instance.backup_for_tools.all()
			self.fields["superuser_on_tools"].initial = self.instance.superuser_for_tools.all()

	def clean(self):
		cleaned_data = super().clean()
		staff_status = cleaned_data.get("is_staff")
		service_personnel_status = cleaned_data.get("is_service_personnel")

		if staff_status and service_personnel_status:
			raise forms.ValidationError(
				{
					"is_staff": "A user cannot be both staff and service personnel. Please choose one or the other.",
					"is_service_personnel": "A user cannot be both staff and service personnel. Please choose one or the other.",
				}
			)


@register(User)
class UserAdmin(admin.ModelAdmin):
	form = UserAdminForm
	filter_horizontal = (
		"groups",
		"user_permissions",
		"qualifications",
		"projects",
		"managed_projects",
		"physical_access_levels",
	)
	fieldsets = (
		(
			"Personal information",
			{"fields": ("first_name", "last_name", "username", "email", "badge_number", "type", "domain")},
		),
		(
			"Permissions",
			{
				"fields": (
					"is_active",
					"is_staff",
					"is_technician",
					"is_service_personnel",
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
					"qualifications",
					"backup_owner_on_tools",
					"superuser_on_tools",
					"projects",
					"managed_projects",
				)
			},
		),
	)
	search_fields = ("first_name", "last_name", "username", "email")
	list_display = (
		"first_name",
		"last_name",
		"username",
		"email",
		"is_active",
		"domain",
		"is_staff",
		"is_technician",
		"is_service_personnel",
		"is_superuser",
		"date_joined",
		"last_login",
	)
	list_filter = (
		"is_active",
		"domain",
		"is_staff",
		"is_technician",
		"is_service_personnel",
		"is_superuser",
		"date_joined",
		"last_login",
	)

	def formfield_for_manytomany(self, db_field, request, **kwargs):
		if db_field.name == "qualifications":
			kwargs["queryset"] = Tool.objects.filter(parent_tool__isnull=True)
		return super().formfield_for_manytomany(db_field, request, **kwargs)

	def save_model(self, request, obj, form, change):
		""" Audit project membership and qualifications when a user is saved. """
		super(UserAdmin, self).save_model(request, obj, form, change)
		record_local_many_to_many_changes(request, obj, form, "projects")
		record_local_many_to_many_changes(request, obj, form, "qualifications")
		record_local_many_to_many_changes(request, obj, form, "physical_access_levels")
		record_active_state(request, obj, form, "is_active", not change)
		if "backup_owner_on_tools" in form.changed_data:
			obj.backup_for_tools.set(form.cleaned_data["backup_owner_on_tools"])
		if "superuser_on_tools" in form.changed_data:
			obj.superuser_for_tools.set(form.cleaned_data["superuser_on_tools"])


@register(PhysicalAccessLog)
class PhysicalAccessLogAdmin(admin.ModelAdmin):
	list_display = ("user", "door", "time", "result")
	list_filter = ("door", "result")
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
	list_filter = ("resolved", "visible", "creation_time", "resolution_time")
	readonly_fields = ("creation_time", "resolution_time")
	search_fields = ("location", "concern", "progress", "resolution")


@register(Door)
class DoorAdmin(admin.ModelAdmin):
	list_display = ("name", "area", "interlock", "get_absolute_url", "id")


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

	physical_access_exceptions = forms.ModelMultipleChoiceField(
		queryset=PhysicalAccessException.objects.all(),
		required=False,
		widget=FilteredSelectMultiple(verbose_name="Physical Access Exceptions", is_stacked=False),
	)

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		if self.instance.pk:
			self.fields["authorized_users"].initial = self.instance.user_set.all()
			self.fields["physical_access_exceptions"].initial = self.instance.physicalaccessexception_set.all()

	def clean(self):
		schedule = self.cleaned_data.get("schedule")
		if schedule == PhysicalAccessLevel.Schedule.WEEKDAYS:
			start_date = self.cleaned_data.get("weekdays_start_time")
			end_date = self.cleaned_data.get("weekdays_end_time")
			if not start_date:
				self.add_error("weekdays_start_time", "Start time is required for weekdays.")
			if not end_date:
				self.add_error("weekdays_end_time", "End time is required for weekdays.")
		else:
			self.cleaned_data["weekdays_start_time"] = None
			self.cleaned_data["weekdays_end_time"] = None
		return self.cleaned_data


@register(PhysicalAccessLevel)
class PhysicalAccessLevelAdmin(admin.ModelAdmin):
	form = PhysicalAccessLevelForm
	list_display = ("name", "area", "get_schedule_display_with_times", "allow_staff_access")
	list_filter = (("area", TreeRelatedFieldListFilter),)

	def save_model(self, request, obj, form, change):
		"""
		Explicitly record any membership changes.
		"""
		record_remote_many_to_many_changes_and_save(request, obj, form, change, "authorized_users", super().save_model)
		if "physical_access_exceptions" in form.changed_data:
			obj.physicalaccessexception_set.set(form.cleaned_data["physical_access_exceptions"])


class PhysicalAccessExceptionAdminForm(forms.ModelForm):
	class Meta:
		model = PhysicalAccessException
		fields = "__all__"

	class Media:
		js = ("admin/time_options_override.js",)

	def clean(self):
		if any(self.errors):
			return
		cleaned_data = super().clean()
		start_time = cleaned_data.get("start_time")
		end_time = cleaned_data.get("end_time")
		if end_time <= start_time:
			self.add_error("end_time", "The end time must be later than the start time")


@register(PhysicalAccessException)
class PhysicalAccessExceptionAdmin(admin.ModelAdmin):
	form = PhysicalAccessExceptionAdminForm
	list_display = ("name", "start_time", "end_time")
	filter_horizontal = ("physical_access_levels",)
	list_filter = ("physical_access_levels__area",)


@register(ContactInformationCategory)
class ContactInformationCategoryAdmin(admin.ModelAdmin):
	list_display = ("name", "display_order")


@register(ContactInformation)
class ContactInformationAdmin(admin.ModelAdmin):
	list_display = ("name", "category", "user")


@register(LandingPageChoice)
class LandingPageChoiceAdmin(admin.ModelAdmin):
	list_display = (
		"display_priority",
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


@register(ScheduledOutageCategory)
class ScheduledOutageCategoryAdmin(admin.ModelAdmin):
	list_display = ("name",)


@register(ScheduledOutage)
class ScheduledOutageAdmin(admin.ModelAdmin):
	list_display = ("id", "tool", "area", "resource", "creator", "title", "start", "end")


@register(News)
class NewsAdmin(admin.ModelAdmin):
	list_display = ("id", "title", "created", "last_updated", "archived", "pinned")
	list_filter = ("archived", "pinned")


@register(Notification)
class NotificationAdmin(admin.ModelAdmin):
	list_display = ("id", "user", "expiration", "content_type", "object_id")


@register(BadgeReader)
class BadgeReaderAdmin(admin.ModelAdmin):
	list_display = ("id", "name", "send_key", "record_key")


class CounterAdminForm(forms.ModelForm):
	class Meta:
		model = ToolUsageCounter
		fields = "__all__"

	def clean(self):
		cleaned_data = super().clean()
		tool = cleaned_data.get("tool")
		tool_usage_question_name = cleaned_data.get("tool_usage_question")
		if tool and tool_usage_question_name:
			error = None
			if tool.post_usage_questions:
				post_usage_form = DynamicForm(tool.post_usage_questions, tool.id)
				tool_question = post_usage_form.filter_questions(
					lambda x: (isinstance(x, PostUsageNumberFieldQuestion) or isinstance(x, PostUsageFloatFieldQuestion)) and x.name == tool_usage_question_name
				)
				if not tool_question:
					candidates = [
						question.name
						for question in post_usage_form.filter_questions(
							lambda x: isinstance(x, PostUsageNumberFieldQuestion) or isinstance(x, PostUsageFloatFieldQuestion)
						)
					]
					error = "The tool has no post usage question of type Number or Float with this name."
					if candidates:
						error += f" Valid question names are: {', '.join(candidates)}"
			else:
				error = "The tool does not have any post usage questions."
			if error:
				self.add_error("tool_usage_question", error)
		return cleaned_data


@register(ToolUsageCounter)
class CounterAdmin(admin.ModelAdmin):
	list_display = (
		"name",
		"tool",
		"tool_usage_question",
		"value",
		"warning_threshold",
		"last_reset",
		"last_reset_by",
		"is_active",
	)
	list_filter = ("tool",)
	readonly_fields = ("warning_threshold_reached",)
	form = CounterAdminForm


@register(BuddyRequest)
class BuddyRequestAdmin(admin.ModelAdmin):
	form = BuddyRequestForm
	list_display = ("user", "start", "end", "area", "reply_count", "expired", "deleted")
	list_filter = ("expired", "deleted")

	def reply_count(self, buddy_request: BuddyRequest):
		return buddy_request.replies.count()

	reply_count.admin_order_field = "replies"
	reply_count.short_description = "Replies"


@register(BuddyRequestMessage)
class BuddyRequestMessageAdmin(admin.ModelAdmin):
	list_display = ("id", "link_to_buddy_request", "author", "creation_date")

	def link_to_buddy_request(self, obj):
		link = reverse("admin:NEMO_buddyrequest_change", args=[obj.buddy_request.id])  # model name has to be lowercase
		return format_html('<a href="%s">%s</a>' % (link, obj.buddy_request))

	link_to_buddy_request.short_description = "BUDDY REQUEST"


@register(EmailLog)
class EmailLogAdmin(admin.ModelAdmin):
	list_display = ["id", "category", "sender", "to", "subject", "when", "ok"]
	list_filter = ["category", "ok"]
	search_fields = ["subject", "content", "to"]
	readonly_fields = ("content_preview",)
	date_hierarchy = "when"

	def content_preview(self, obj):
		return mark_safe(obj.content)

	def has_delete_permission(self, request, obj=None):
		return False

	def has_add_permission(self, request):
		return False

	def has_change_permission(self, request, obj=None):
		return False


admin.site.register(AccountType)
admin.site.register(ResourceCategory)
admin.site.register(Permission)
