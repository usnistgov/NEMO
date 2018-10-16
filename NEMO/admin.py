from django import forms
from django.contrib import admin
from django.contrib.admin import register
from django.contrib.admin.widgets import FilteredSelectMultiple
from django.contrib.auth.models import Permission

from NEMO.actions import lock_selected_interlocks, unlock_selected_interlocks
from NEMO.models import Account, ActivityHistory, Alert, Area, AreaAccessRecord, Comment, Configuration, ConfigurationHistory, Consumable, ConsumableCategory, ConsumableWithdraw, ContactInformation, ContactInformationCategory, Customization, Door, Interlock, InterlockCard, LandingPageChoice, MembershipHistory, PhysicalAccessLevel, PhysicalAccessLog, Project, Reservation, Resource, ResourceCategory, SafetyIssue, ScheduledOutage, ScheduledOutageCategory, StaffCharge, Task, TaskCategory, TaskHistory, TaskStatus, Tool, TrainingSession, UsageEvent, User, UserType, News, Notification

admin.site.site_header = "NEMO"
admin.site.site_title = "NEMO"
admin.site.index_title = "Detailed administration"


def record_remote_many_to_many_changes_and_save(request, obj, form, change, many_to_many_field, save_function_pointer):
	"""
	Record the changes in a many-to-many field that the model does not own. Then, save the many-to-many field.
	"""
	# If the model object is being changed then we can get the list of previous members.
	if change:
		original_members = set(obj.user_set.all())
	else:  # The model object is being created (instead of changed) so we can assume there are no members (initially).
		original_members = set()
	current_members = set(form.cleaned_data[many_to_many_field])
	added_members = []
	removed_members = []

	# Log membership changes if they occurred.
	symmetric_difference = original_members ^ current_members
	if symmetric_difference:
		if change:  # the members have changed, so find out what was added and removed...
			# We can can see the previous members of the object model by looking it up
			# in the database because the member list hasn't been committed yet.
			added_members = set(current_members) - set(original_members)
			removed_members = set(original_members) - set(current_members)

		else:  # a model object is being created (instead of changed) so we can assume all the members are new...
			added_members = form.cleaned_data[many_to_many_field]

	# A primary key for the object is required to make many-to-many field changes.
	# If the object is being changed then it has already been assigned a primary key.
	if not change:
		save_function_pointer(request, obj, form, change)
	obj.user_set = form.cleaned_data[many_to_many_field]
	save_function_pointer(request, obj, form, change)

	# Record which members were added to the object.
	for user in added_members:
		new_member = MembershipHistory()
		new_member.authorizer = request.user
		new_member.parent_content_object = obj
		new_member.child_content_object = user
		new_member.action = MembershipHistory.Action.ADDED
		new_member.save()

	# Record which members were removed from the object.
	for user in removed_members:
		ex_member = MembershipHistory()
		ex_member.authorizer = request.user
		ex_member.parent_content_object = obj
		ex_member.child_content_object = user
		ex_member.action = MembershipHistory.Action.REMOVED
		ex_member.save()


def record_local_many_to_many_changes(request, obj, form, many_to_many_field):
	"""
	Record the changes in a many-to-many field that the model owns.
	"""
	if many_to_many_field in form.changed_data:
		original_members = set(getattr(obj, many_to_many_field).all())
		current_members = set(form.cleaned_data[many_to_many_field])
		added_members = set(current_members) - set(original_members)
		for a in added_members:
			p = MembershipHistory()
			p.action = MembershipHistory.Action.ADDED
			p.authorizer = request.user
			p.child_content_object = obj
			p.parent_content_object = a
			p.save()
		removed_members = set(original_members) - set(current_members)
		for a in removed_members:
			p = MembershipHistory()
			p.action = MembershipHistory.Action.REMOVED
			p.authorizer = request.user
			p.child_content_object = obj
			p.parent_content_object = a
			p.save()


def record_active_state(request, obj, form, field_name, is_initial_creation):
	"""
	Record whether the account, project, or user is active when the active state is changed.
	"""
	if field_name in form.changed_data or is_initial_creation:
		activity_entry = ActivityHistory()
		activity_entry.authorizer = request.user
		activity_entry.action = getattr(obj, field_name)
		activity_entry.content_object = obj
		activity_entry.save()


class ToolAdminForm(forms.ModelForm):
	class Meta:
		model = Tool
		fields = '__all__'

	qualified_users = forms.ModelMultipleChoiceField(
		queryset=User.objects.all(),
		required=False,
		widget=FilteredSelectMultiple(
			verbose_name='Users',
			is_stacked=False
		)
	)

	backup_owners = forms.ModelMultipleChoiceField(
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


@register(Tool)
class ToolAdmin(admin.ModelAdmin):
	list_display = ('name', 'category', 'visible', 'operational', 'problematic', 'is_configurable')
	list_filter = ('visible', 'operational', 'category')
	form = ToolAdminForm
	fieldsets = (
		(None, {'fields': ('name', 'category', 'qualified_users', 'post_usage_questions'),}),
		('Current state', {'fields': ('visible', 'operational'),}),
		('Contact information', {'fields': ('primary_owner', 'backup_owners', 'notification_email_address', 'location', 'phone_number'),}),
		('Usage policy', {'fields': ('reservation_horizon', 'minimum_usage_block_time', 'maximum_usage_block_time', 'maximum_reservations_per_day', 'minimum_time_between_reservations', 'maximum_future_reservation_time', 'missed_reservation_threshold', 'requires_area_access', 'interlock', 'allow_delayed_logoff'),}),
		('Dependencies', {'fields': ('required_resources', 'nonrequired_resources'),}),
	)

	def save_model(self, request, obj, form, change):
		"""
		Explicitly record any project membership changes.
		"""
		record_remote_many_to_many_changes_and_save(request, obj, form, change, 'qualified_users', super(ToolAdmin, self).save_model)
		if 'required_resources' in form.changed_data:
			obj.required_resource_set = form.cleaned_data['required_resources']
		if 'nonrequired_resources' in form.changed_data:
			obj.nonrequired_resource_set = form.cleaned_data['nonrequired_resources']


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
	list_display = ('name', 'quantity', 'category', 'visible', 'reminder_threshold', 'reminder_email')
	list_filter = ('visible', 'category')


@register(ConsumableCategory)
class ConsumableCategoryAdmin(admin.ModelAdmin):
	list_display = ('name',)


@register(ConsumableWithdraw)
class ConsumableWithdrawAdmin(admin.ModelAdmin):
	list_display = ('id', 'customer', 'merchant', 'consumable', 'quantity', 'project', 'date')
	list_filter = ('date', 'consumable')
	date_hierarchy = 'date'


@register(InterlockCard)
class InterlockCardAdmin(admin.ModelAdmin):
	list_display = ('server', 'port', 'number', 'even_port', 'odd_port')


@register(Interlock)
class InterlockAdmin(admin.ModelAdmin):
	list_display = ('id', 'card', 'channel', 'state', 'tool', 'door')
	actions = [lock_selected_interlocks, unlock_selected_interlocks]
	readonly_fields = ['state', 'most_recent_reply']


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


@register(Comment)
class CommentAdmin(admin.ModelAdmin):
	list_display = ('id', 'tool', 'author', 'creation_date', 'expiration_date', 'visible', 'hidden_by', 'hide_date')
	list_filter = ('visible', 'creation_date', 'tool')
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


@register(User)
class UserAdmin(admin.ModelAdmin):
	filter_horizontal = ('groups', 'user_permissions', 'qualifications', 'projects', 'physical_access_levels')
	fieldsets = (
		('Personal information', {'fields': ('first_name', 'last_name', 'username', 'email', 'badge_number', 'type', 'domain')}),
		('Permissions', {'fields': ('is_active', 'is_staff', 'is_technician', 'is_superuser', 'training_required', 'groups', 'user_permissions', 'physical_access_levels')}),
		('Important dates', {'fields': ('date_joined', 'last_login', 'access_expiration')}),
		('NanoFab information', {'fields': ('qualifications', 'projects')}),
	)
	search_fields = ('first_name', 'last_name', 'username', 'email')
	list_display = ('first_name', 'last_name', 'username', 'email', 'is_active', 'domain', 'is_staff', 'is_technician', 'is_superuser', 'date_joined', 'last_login')
	list_filter = ('is_active', 'domain', 'is_staff', 'is_technician', 'is_superuser', 'date_joined', 'last_login')

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
	list_display = ('name', 'area', 'interlock', 'get_absolute_url')


@register(Alert)
class AlertAdmin(admin.ModelAdmin):
	list_display = ('title', 'creation_time', 'creator', 'debut_time', 'expiration_time', 'user', 'dismissible')


@register(PhysicalAccessLevel)
class PhysicalAccessLevelAdmin(admin.ModelAdmin):
	list_display = ('name', 'area', 'schedule')


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
	list_display = ('id', 'tool', 'resource', 'creator', 'title', 'start', 'end')


@register(News)
class NewsAdmin(admin.ModelAdmin):
	list_display = ('id', 'created', 'last_updated', 'archived', 'title')
	list_filter = ('archived',)


@register(Notification)
class NotificationAdmin(admin.ModelAdmin):
	list_display = ('id', 'user', 'expiration', 'content_type', 'object_id')


admin.site.register(ResourceCategory)
admin.site.register(Area)
admin.site.register(Permission)
