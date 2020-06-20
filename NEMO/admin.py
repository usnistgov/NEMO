from json import loads
from django import forms
from django.contrib import admin
from django.contrib.admin import register
from django.contrib.admin.widgets import FilteredSelectMultiple
from django.contrib.auth.models import Permission
from django.db.models.fields.files import FieldFile
from django.utils.html import format_html

from NEMO.actions import lock_selected_interlocks, synchronize_with_tool_usage, unlock_selected_interlocks, \
	duplicate_tool_configuration
from NEMO.models import Account, ActivityHistory, Alert, Area, AreaAccessRecord, Comment, Configuration, \
	ConfigurationHistory, Consumable, ConsumableCategory, ConsumableWithdraw, ContactInformation, \
	ContactInformationCategory, Customization, Door, Interlock, InterlockCard, LandingPageChoice, MembershipHistory, \
	News, Notification, PhysicalAccessLevel, PhysicalAccessLog, Project, Reservation, Resource, ResourceCategory, \
	SafetyIssue, ScheduledOutage, ScheduledOutageCategory, StaffCharge, Task, TaskCategory, TaskHistory, TaskStatus, \
	Tool, TrainingSession, UsageEvent, User, UserType, UserPreferences, TaskImages, InterlockCardCategory, \
	record_remote_many_to_many_changes_and_save, record_local_many_to_many_changes, record_active_state, AlertCategory
from NEMO.widgets.dynamic_form import DynamicForm


class ToolAdminForm(forms.ModelForm):
	class Meta:
		model = Tool
		fields = '__all__'

	class Media:
		js = ("tool_form_admin.js",)
		css = {'':('tool_form_admin.css',),}

	qualified_users = forms.ModelMultipleChoiceField(
		queryset=User.objects.all(),
		required=False,
		widget=FilteredSelectMultiple(
			verbose_name='Users',
			is_stacked=False
		)
	)

	_backup_owners = forms.ModelMultipleChoiceField(
		queryset=User.objects.all(),
		required=False,
		widget=FilteredSelectMultiple(
			verbose_name='Users',
			is_stacked=False
		)
	)

	required_resources = forms.ModelMultipleChoiceField(
		queryset=Resource.objects.all(),
		required=False,
		widget=FilteredSelectMultiple(
			verbose_name='Required resources',
			is_stacked=False
		)
	)

	nonrequired_resources = forms.ModelMultipleChoiceField(
		queryset=Resource.objects.all(),
		required=False,
		widget=FilteredSelectMultiple(
			verbose_name='Nonrequired resources',
			is_stacked=False
		)
	)

	def __init__(self, *args, **kwargs):
		super(ToolAdminForm, self).__init__(*args, **kwargs)
		if self.instance.pk:
			self.fields['qualified_users'].initial = self.instance.user_set.all()
			self.fields['required_resources'].initial = self.instance.required_resource_set.all()
			self.fields['nonrequired_resources'].initial = self.instance.nonrequired_resource_set.all()


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
			cleaned_data['_image'] = resize_image(image, 500)

		if parent_tool:
			if parent_tool.id == self.instance.id:
				self.add_error('parent_tool', 'You cannot select the parent to be the tool itself.')
			# in case of alternate tool, remove everything except parent_tool and name
			data = dict([(k, v) for k, v in self.cleaned_data.items() if k == "parent_tool" or k == "name"])
			# an alternate tool is never visible
			data['visible'] = False
			return data
		else:
			if not category:
				self.add_error('_category', 'This field is required.')
			if not location:
				self.add_error('_location', 'This field is required.')
			if not phone_number:
				self.add_error('_phone_number', 'This field is required.')
			if not primary_owner:
				self.add_error('_primary_owner', 'This field is required.')

			post_usage_questions = cleaned_data.get("_post_usage_questions")
			# Validate _post_usage_questions JSON format
			if post_usage_questions:
				try:
					loads(post_usage_questions)
				except ValueError as error:
					self.add_error("_post_usage_questions", "This field needs to be a valid JSON string")
					
			policy_off_between_times = cleaned_data.get("_policy_off_between_times")
			policy_off_start_time = cleaned_data.get("_policy_off_start_time")
			policy_off_end_time = cleaned_data.get("_policy_off_end_time")
			if policy_off_between_times and (not policy_off_start_time or not policy_off_end_time):
				if not policy_off_start_time:
					self.add_error("_policy_off_start_time", "Start time must be specified")
				if not policy_off_end_time:
					self.add_error("_policy_off_end_time", "End time must be specified")


@register(Tool)
class ToolAdmin(admin.ModelAdmin):
	list_display = ('name_display', '_category', 'visible', 'operational_display', 'problematic', 'is_configurable', 'id')
	search_fields = ('name', '_description', '_serial')
	list_filter = ('visible', '_operational', '_category', '_location')
	readonly_fields = ('_post_usage_preview',)
	actions = [duplicate_tool_configuration]
	form = ToolAdminForm
	fieldsets = (
		(None, {'fields': ('name', 'parent_tool', '_category', 'qualified_users', '_post_usage_questions', '_post_usage_preview'),}),
		('Additional Information', {'fields': ('_description', '_serial', '_image'),}),
		('Current state', {'fields': ('visible', '_operational'),}),
		('Contact information', {'fields': ('_primary_owner', '_backup_owners', '_notification_email_address', '_location', '_phone_number'),}),
		('Reservation', {'fields': ('_reservation_horizon', '_missed_reservation_threshold'),}),
		('Usage policy', {'fields': ('_policy_off_between_times', '_policy_off_start_time', '_policy_off_end_time', '_policy_off_weekend', '_minimum_usage_block_time', '_maximum_usage_block_time', '_maximum_reservations_per_day', '_minimum_time_between_reservations', '_maximum_future_reservation_time',),}),
		('Area Access', {'fields': ('_requires_area_access', '_grant_physical_access_level_upon_qualification', '_grant_badge_reader_access_upon_qualification', '_interlock', '_allow_delayed_logoff'),}),
		('Dependencies', {'fields': ('required_resources', 'nonrequired_resources'),}),
	)

	def _post_usage_preview(self, obj):
		form_validity_div = '<div id="form_validity"></div>' if obj.post_usage_questions else ''
		return format_html('<div class="post_usage_preview">{}{}</div><div class="help post_usage_preview_help">Save form to preview post usage questions</div>'.format(DynamicForm(obj.post_usage_questions).render(), form_validity_div))

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
			record_remote_many_to_many_changes_and_save(request, obj, form, change, 'qualified_users', super(ToolAdmin, self).save_model)
			if 'required_resources' in form.changed_data:
				obj.required_resource_set.set(form.cleaned_data['required_resources'])
			if 'nonrequired_resources' in form.changed_data:
				obj.nonrequired_resource_set.set(form.cleaned_data['nonrequired_resources'])


@register(Area)
class AreaAdmin(admin.ModelAdmin):
	list_display = ('name', 'parent_area', 'category', 'requires_reservation', 'maximum_capacity', 'reservation_warning', 'id')
	fieldsets = (
		(None, {'fields': ('name', 'parent_area', 'category'),}),
		('Area access', {'fields': ('requires_reservation', 'logout_grace_period', 'welcome_message'),}),
		('Occupancy', {'fields': ('maximum_capacity', 'count_staff_in_occupancy', 'reservation_warning'),}),
		('Reservation', {'fields': ('reservation_horizon', 'missed_reservation_threshold'),}),
		('Policy', {'fields': ('policy_off_between_times', 'policy_off_start_time', 'policy_off_end_time', 'policy_off_weekend', 'minimum_usage_block_time', 'maximum_usage_block_time', 'maximum_reservations_per_day', 'minimum_time_between_reservations', 'maximum_future_reservation_time',),}),
	)
	list_filter = ('requires_reservation', 'parent_area',)
	search_fields = ('name',)

	def get_fieldsets(self, request, obj:Area=None):
		"""
		Remove some fieldsets if this area is a parent
		"""
		if obj and obj.area_children_set.all().exists():
			return [i for i in self.fieldsets if i[0] not in ['Area access', 'Reservation', 'Policy']]
		return super().get_fieldsets(request, obj)

	def save_model(self, request, obj:Area, form, change):
		"""
		Explicitly record any project membership changes.
		"""
		if obj.parent_area:
			# if this area has a parent, that parent needs to be cleaned and updated
			obj.parent_area.is_now_a_parent()
		super(AreaAdmin, self).save_model(request, obj, form, change)


@register(TrainingSession)
class TrainingSessionAdmin(admin.ModelAdmin):
	list_display = ('id', 'trainer', 'trainee', 'tool', 'project', 'type', 'date', 'duration', 'qualified')
	list_filter = ('qualified', 'date', 'type', 'tool')
	date_hierarchy = 'date'


@register(StaffCharge)
class StaffChargeAdmin(admin.ModelAdmin):
	list_display = ('id', 'staff_member', 'customer', 'start', 'end')
	list_filter = ('start',)
	date_hierarchy = 'start'


@register(AreaAccessRecord)
class AreaAccessRecordAdmin(admin.ModelAdmin):
	list_display = ('id', 'customer', 'area', 'project', 'start', 'end')
	list_filter = ('area', 'start',)
	date_hierarchy = 'start'


@register(Configuration)
class ConfigurationAdmin(admin.ModelAdmin):
	list_display = ('id', 'tool', 'name', 'qualified_users_are_maintainers', 'display_priority', 'exclude_from_configuration_agenda')
	filter_horizontal = ('maintainers',)


@register(ConfigurationHistory)
class ConfigurationHistoryAdmin(admin.ModelAdmin):
	list_display = ('id', 'configuration', 'user', 'modification_time', 'slot')
	date_hierarchy = 'modification_time'


@register(Account)
class AccountAdmin(admin.ModelAdmin):
	list_display = ('name', 'id', 'active')
	search_fields = ('name',)
	list_filter = ('active',)

	def save_model(self, request, obj, form, change):
		""" Audit account and project active status. """
		super(AccountAdmin, self).save_model(request, obj, form, change)
		record_active_state(request, obj, form, 'active', not change)


class ProjectAdminForm(forms.ModelForm):
	class Meta:
		model = Project
		fields = '__all__'

	members = forms.ModelMultipleChoiceField(
		queryset=User.objects.all(),
		required=False,
		widget=FilteredSelectMultiple(
			verbose_name='Users',
			is_stacked=False
		)
	)

	def __init__(self, *args, **kwargs):
		super(ProjectAdminForm, self).__init__(*args, **kwargs)
		if self.instance.pk:
			self.fields['members'].initial = self.instance.user_set.all()


@register(Project)
class ProjectAdmin(admin.ModelAdmin):
	list_display = ('name', 'id', 'application_identifier', 'account', 'active')
	search_fields = ('name', 'application_identifier', 'account__name')
	list_filter = ('active',)
	form = ProjectAdminForm

	def save_model(self, request, obj, form, change):
		"""
		Audit project creation and modification. Also save any project membership changes explicitly.
		"""
		record_remote_many_to_many_changes_and_save(request, obj, form, change, 'members', super(ProjectAdmin, self).save_model)
		# Make a history entry if a project has been moved under an account.
		# This applies to newly created projects and project ownership reassignment.
		if 'account' in form.changed_data:
			# Create a membership removal entry for the project if it used to belong to another account:
			if change:
				previous_account = MembershipHistory()
				previous_account.authorizer = request.user
				previous_account.child_content_object = obj
				previous_account.parent_content_object = Account.objects.get(pk=form.initial['account'])
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
		record_active_state(request, obj, form, 'active', not change)


@register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
	list_display = ('id', 'user', 'creator', 'tool', 'project', 'start', 'end', 'duration', 'cancelled', 'missed')
	list_filter = ('cancelled', 'missed', 'tool')
	date_hierarchy = 'start'


@register(UsageEvent)
class UsageEventAdmin(admin.ModelAdmin):
	list_display = ('id', 'tool', 'user', 'operator', 'project', 'start', 'end', 'duration')
	list_filter = ('start', 'end', 'tool')
	date_hierarchy = 'start'


@register(Consumable)
class ConsumableAdmin(admin.ModelAdmin):
	list_display = ('name', 'quantity', 'category', 'visible', 'reminder_threshold', 'reminder_email', 'id')
	list_filter = ('visible', 'category')


@register(ConsumableCategory)
class ConsumableCategoryAdmin(admin.ModelAdmin):
	list_display = ('name',)


@register(ConsumableWithdraw)
class ConsumableWithdrawAdmin(admin.ModelAdmin):
	list_display = ('id', 'customer', 'merchant', 'consumable', 'quantity', 'project', 'date')
	list_filter = ('date', 'consumable')
	date_hierarchy = 'date'


class InterlockCardAdminForm(forms.ModelForm):
	class Meta:
		model = InterlockCard
		widgets = {
			'password': forms.PasswordInput(render_value=True),
		}
		fields = '__all__'

	def clean(self):
		if any(self.errors):
			return
		super(InterlockCardAdminForm, self).clean()
		category = self.cleaned_data['category']
		from NEMO import interlocks
		interlocks.get(category, False).clean_interlock_card(self)


@register(InterlockCard)
class InterlockCardAdmin(admin.ModelAdmin):
	form = InterlockCardAdminForm
	list_display = ('name', 'server', 'port', 'number', 'category', 'even_port', 'odd_port')


class InterlockAdminForm(forms.ModelForm):
	class Meta:
		model = Interlock
		fields = '__all__'

	def clean(self):
		if any(self.errors):
			return
		super(InterlockAdminForm, self).clean()
		from NEMO import interlocks
		category = self.cleaned_data['card'].category
		interlocks.get(category, False).clean_interlock(self)


@register(Interlock)
class InterlockAdmin(admin.ModelAdmin):
	form = InterlockAdminForm
	list_display = ('id', 'card', 'channel', 'state', 'tool', 'door')
	actions = [lock_selected_interlocks, unlock_selected_interlocks, synchronize_with_tool_usage]
	readonly_fields = ['state', 'most_recent_reply']


@register(InterlockCardCategory)
class InterlockCardCategoryAdmin(admin.ModelAdmin):
	list_display = ('name',)


@register(Task)
class TaskAdmin(admin.ModelAdmin):
	list_display = ('id', 'urgency', 'tool', 'creator', 'creation_time', 'problem_category', 'cancelled', 'resolved', 'resolution_category')
	list_filter = ('urgency', 'resolved', 'cancelled', 'safety_hazard', 'creation_time', 'tool')
	date_hierarchy = 'creation_time'


@register(TaskCategory)
class TaskCategoryAdmin(admin.ModelAdmin):
	list_display = ('name', 'stage')


@register(TaskStatus)
class TaskStatusAdmin(admin.ModelAdmin):
	list_display = ('name', 'notify_primary_tool_owner', 'notify_backup_tool_owners', 'notify_tool_notification_email', 'custom_notification_email_address')


@register(TaskHistory)
class TaskHistoryAdmin(admin.ModelAdmin):
	list_display = ('id', 'task', 'status', 'time', 'user')
	readonly_fields = ('time',)
	date_hierarchy = 'time'


@register(TaskImages)
class TaskImagesAdmin(admin.ModelAdmin):
	list_display = ('id', 'get_tool', 'task', 'uploaded_at')

	def get_tool(self, task_image: TaskImages):
		return task_image.task.tool.name
	get_tool.admin_order_field = 'tool'  # Allows column order sorting
	get_tool.short_description = 'Tool Name'  # Renames column head


@register(Comment)
class CommentAdmin(admin.ModelAdmin):
	list_display = ('id', 'tool', 'author', 'creation_date', 'expiration_date', 'visible', 'staff_only', 'hidden_by', 'hide_date')
	list_filter = ('visible', 'creation_date', 'tool', 'staff_only')
	date_hierarchy = 'creation_date'
	search_fields = ('content',)


@register(Resource)
class ResourceAdmin(admin.ModelAdmin):
	list_display = ('name', 'category', 'available')
	list_filter = ('available', 'category')
	filter_horizontal = ('fully_dependent_tools', 'partially_dependent_tools', 'dependent_areas')


@register(ActivityHistory)
class ActivityHistoryAdmin(admin.ModelAdmin):
	list_display = ('__str__', 'content_type', 'object_id', 'action', 'date', 'authorizer')
	date_hierarchy = 'date'


@register(MembershipHistory)
class MembershipHistoryAdmin(admin.ModelAdmin):
	list_display = ('__str__', 'parent_content_type', 'parent_object_id', 'action', 'child_content_type', 'child_object_id', 'date', 'authorizer')
	date_hierarchy = 'date'


@register(UserType)
class UserTypeAdmin(admin.ModelAdmin):
	list_display = ('name',)


@register(UserPreferences)
class UserPreferencesAdmin(admin.ModelAdmin):
	list_display = ('user',)


@register(User)
class UserAdmin(admin.ModelAdmin):
	filter_horizontal = ('groups', 'user_permissions', 'qualifications', 'projects', 'physical_access_levels')
	fieldsets = (
		('Personal information', {'fields': ('first_name', 'last_name', 'username', 'email', 'badge_number', 'type', 'domain')}),
		('Permissions', {'fields': ('is_active', 'is_staff', 'is_technician', 'is_superuser', 'training_required', 'groups', 'user_permissions', 'physical_access_levels')}),
		('Important dates', {'fields': ('date_joined', 'last_login', 'access_expiration')}),
		("Facility information", {'fields': ('qualifications', 'projects')}),
	)
	search_fields = ('first_name', 'last_name', 'username', 'email')
	list_display = ('first_name', 'last_name', 'username', 'email', 'is_active', 'domain', 'is_staff', 'is_technician', 'is_superuser', 'date_joined', 'last_login')
	list_filter = ('is_active', 'domain', 'is_staff', 'is_technician', 'is_superuser', 'date_joined', 'last_login')

	def formfield_for_manytomany(self, db_field, request, **kwargs):
		if db_field.name == "qualifications":
			kwargs["queryset"] = Tool.objects.filter(parent_tool__isnull=True)
		return super().formfield_for_manytomany(db_field, request, **kwargs)

	def save_model(self, request, obj, form, change):
		""" Audit project membership and qualifications when a user is saved. """
		super(UserAdmin, self).save_model(request, obj, form, change)
		record_local_many_to_many_changes(request, obj, form, 'projects')
		record_local_many_to_many_changes(request, obj, form, 'qualifications')
		record_local_many_to_many_changes(request, obj, form, 'physical_access_levels')
		record_active_state(request, obj, form, 'is_active', not change)


@register(PhysicalAccessLog)
class PhysicalAccessLogAdmin(admin.ModelAdmin):
	list_display = ('user', 'door', 'time', 'result')
	list_filter = ('door', 'result')
	search_fields = ('user',)
	date_hierarchy = 'time'


@register(SafetyIssue)
class SafetyIssueAdmin(admin.ModelAdmin):
	list_display = ('id', 'reporter', 'creation_time', 'visible', 'resolved', 'resolution_time', 'resolver')
	list_filter = ('resolved', 'visible', 'creation_time', 'resolution_time')
	readonly_fields = ('creation_time', 'resolution_time')
	search_fields = ('location', 'concern', 'progress', 'resolution',)


@register(Door)
class DoorAdmin(admin.ModelAdmin):
	list_display = ('name', 'area', 'interlock', 'get_absolute_url', 'id')


@register(AlertCategory)
class AlertCategoryAdmin(admin.ModelAdmin):
	list_display = ('name',)


class AlertAdminForm(forms.ModelForm):
	contents = forms.CharField(widget=forms.Textarea(attrs={'rows':3, 'cols': 50}),)

	class Meta:
		model = Alert
		fields = '__all__'


@register(Alert)
class AlertAdmin(admin.ModelAdmin):
	list_display = ('title', 'category', 'creation_time', 'creator', 'debut_time', 'expiration_time', 'user', 'dismissible', 'expired', 'deleted')
	form = AlertAdminForm


class PhysicalAccessLevelForm(forms.ModelForm):
	class Meta:
		model = PhysicalAccessLevel
		fields = '__all__'

	authorized_users = forms.ModelMultipleChoiceField(
		queryset=User.objects.all(),
		required=False,
		widget=FilteredSelectMultiple(
			verbose_name='Users',
			is_stacked=False
		)
	)

	def __init__(self, *args, **kwargs):
		super(PhysicalAccessLevelForm, self).__init__(*args, **kwargs)
		if self.instance.pk:
			self.fields['authorized_users'].initial = self.instance.user_set.all()


@register(PhysicalAccessLevel)
class PhysicalAccessLevelAdmin(admin.ModelAdmin):
	form = PhysicalAccessLevelForm
	list_display = ('name', 'area', 'schedule', 'allow_staff_access')

	def save_model(self, request, obj, form, change):
		"""
		Explicitly record any membership changes.
		"""
		record_remote_many_to_many_changes_and_save(request, obj, form, change, 'authorized_users', super(PhysicalAccessLevelAdmin, self).save_model)


@register(ContactInformationCategory)
class ContactInformationCategoryAdmin(admin.ModelAdmin):
	list_display = ('name', 'display_order')


@register(ContactInformation)
class ContactInformationAdmin(admin.ModelAdmin):
	list_display = ('name', 'category')


@register(LandingPageChoice)
class LandingPageChoiceAdmin(admin.ModelAdmin):
	list_display = ('display_priority', 'name', 'url', 'open_in_new_tab', 'secure_referral', 'hide_from_mobile_devices', 'hide_from_desktop_computers')
	list_display_links = ('name',)


@register(Customization)
class CustomizationAdmin(admin.ModelAdmin):
	list_display = ('name', 'value')


@register(ScheduledOutageCategory)
class ScheduledOutageCategoryAdmin(admin.ModelAdmin):
	list_display = ('name',)


@register(ScheduledOutage)
class ScheduledOutageAdmin(admin.ModelAdmin):
	list_display = ('id', 'tool', 'area', 'resource', 'creator', 'title', 'start', 'end')


@register(News)
class NewsAdmin(admin.ModelAdmin):
	list_display = ('id', 'created', 'last_updated', 'archived', 'title')
	list_filter = ('archived',)


@register(Notification)
class NotificationAdmin(admin.ModelAdmin):
	list_display = ('id', 'user', 'expiration', 'content_type', 'object_id')


admin.site.register(ResourceCategory)
admin.site.register(Permission)
