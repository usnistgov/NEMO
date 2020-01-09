import datetime
import os
from datetime import timedelta

from django.contrib import auth
from django.contrib.auth.models import BaseUserManager, Group, Permission
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models import Q
from django.db.models.signals import pre_delete
from django.dispatch import receiver
from django.urls import reverse
from django.utils import timezone

from NEMO.utilities import send_mail, get_task_image_filename
from NEMO.views.constants import ADDITIONAL_INFORMATION_MAXIMUM_LENGTH
from NEMO.widgets.configuration_editor import ConfigurationEditor


class CalendarDisplay(models.Model):
	"""
	Inherit from this class to express that a class type is able to be displayed in the NEMO calendar.
	Calling get_visual_end() will artificially lengthen the end time so the event is large enough to
	be visible and clickable.
	"""
	start = None
	end = None

	def get_visual_end(self):
		if self.end is None:
			return max(self.start + timedelta(minutes=15), timezone.now())
		else:
			return max(self.start + timedelta(minutes=15), self.end)

	class Meta:
		abstract = True


class UserPreferences(models.Model):
	attach_created_reservation = models.BooleanField('created_reservation_invite', default=False, help_text='Whether or not to send a calendar invitation when creating a new reservation')
	attach_cancelled_reservation = models.BooleanField('cancelled_reservation_invite', default=False, help_text='Whether or not to send a calendar invitation when cancelling a reservation')

	class Meta:
		verbose_name = 'User preferences'
		verbose_name_plural = 'User preferences'


class UserManager(BaseUserManager):
	def create_user(self, username, first_name, last_name, email):
		user = User()
		user.username = username
		user.first_name = first_name
		user.last_name = last_name
		user.email = email
		user.date_joined = timezone.now()
		user.save()
		return user

	def create_superuser(self, username, first_name, last_name, email, password=None):
		user = self.create_user(username, first_name, last_name, email)
		user.is_superuser = True
		user.is_staff = True
		user.training_required = False
		user.save()
		return user


class UserType(models.Model):
	name = models.CharField(max_length=50, unique=True)

	def __str__(self):
		return self.name

	class Meta:
		ordering = ['name']


class User(models.Model):
	# Personal information:
	username = models.CharField(max_length=100, unique=True)
	first_name = models.CharField(max_length=100)
	last_name = models.CharField(max_length=100)
	email = models.EmailField(verbose_name='email address')
	type = models.ForeignKey(UserType, null=True, on_delete=models.SET_NULL)
	domain = models.CharField(max_length=100, blank=True, help_text="The Active Directory domain that the account resides on")

	# Physical access fields
	badge_number = models.PositiveIntegerField(null=True, blank=True, unique=True, help_text="The badge number associated with this user. This number must correctly correspond to a user in order for the tablet-login system (in the NanoFab lobby) to work properly.")
	access_expiration = models.DateField(blank=True, null=True, help_text="The user will lose all access rights after this date. Typically this is used to ensure that safety training has been completed by the user every year.")
	physical_access_levels = models.ManyToManyField('PhysicalAccessLevel', blank=True, related_name='users')

	# Permissions
	is_active = models.BooleanField('active', default=True, help_text='Designates whether this user can log in to NEMO. Unselect this instead of deleting accounts.')
	is_staff = models.BooleanField('staff status', default=False, help_text='Designates whether the user can log into this admin site.')
	is_technician = models.BooleanField('technician status', default=False, help_text='Specifies how to bill staff time for this user. When checked, customers are billed at technician rates.')
	is_superuser = models.BooleanField('superuser status', default=False, help_text='Designates that this user has all permissions without explicitly assigning them.')
	training_required = models.BooleanField(default=True, help_text='When selected, the user is blocked from all reservation and tool usage capabilities.')
	groups = models.ManyToManyField(Group, blank=True, help_text='The groups this user belongs to. A user will get all permissions granted to each of his/her group.')
	user_permissions = models.ManyToManyField(Permission, blank=True, help_text='Specific permissions for this user.')

	# Important dates
	date_joined = models.DateTimeField(default=timezone.now)
	last_login = models.DateTimeField(null=True, blank=True)

	# NanoFab information:
	qualifications = models.ManyToManyField('Tool', blank=True, help_text='Select the tools that the user is qualified to use.')
	projects = models.ManyToManyField('Project', blank=True, help_text='Select the projects that this user is currently working on.')

	# Preferences
	preferences: UserPreferences = models.OneToOneField(UserPreferences, null=True, on_delete=models.SET_NULL)

	USERNAME_FIELD = 'username'
	REQUIRED_FIELDS = ['first_name', 'last_name', 'email']
	objects = UserManager()

	def has_perm(self, perm, obj=None):
		"""
		Returns True if the user has each of the specified permissions. If
		object is passed, it checks if the user has all required perms for this object.
		"""

		# Active superusers have all permissions.
		if self.is_active and self.is_superuser:
			return True

		# Otherwise we need to check the backends.
		for backend in auth.get_backends():
			if hasattr(backend, "has_perm"):
				if obj is not None:
					if backend.has_perm(self, perm, obj):
						return True
				else:
					if backend.has_perm(self, perm):
						return True
		return False

	def has_perms(self, perm_list, obj=None):
		for perm in perm_list:
			if not self.has_perm(perm, obj):
				return False
		return True

	def has_module_perms(self, app_label):
		"""
		Returns True if the user has any permissions in the given app label.
		Uses pretty much the same logic as has_perm, above.
		"""
		# Active superusers have all permissions.
		if self.is_active and self.is_superuser:
			return True

		for backend in auth.get_backends():
			if hasattr(backend, "has_module_perms"):
				if backend.has_module_perms(self, app_label):
					return True
		return False

	def check_password(self, raw_password):
		return False

	@property
	def is_authenticated(self):
		return True

	@property
	def is_anonymous(self):
		return False

	def get_username(self):
		return self.username

	def email_user(self, subject, message, from_email, attachments=None):
		""" Sends an email to this user. """
		send_mail(subject=subject, message=message, from_email=from_email, recipient_list=[self.email], attachments=attachments)

	def get_full_name(self):
		return self.first_name + ' ' + self.last_name + ' (' + self.username + ')'

	def get_short_name(self):
		return self.first_name

	def in_area(self):
		return AreaAccessRecord.objects.filter(customer=self, staff_charge=None, end=None).exists()

	def area_access_record(self):
		try:
			return AreaAccessRecord.objects.get(customer=self, staff_charge=None, end=None)
		except AreaAccessRecord.DoesNotExist:
			return None

	def billing_to_project(self):
		access_record = self.area_access_record()
		if access_record is None:
			return None
		else:
			return access_record.project

	def active_project_count(self):
		return self.projects.filter(active=True, account__active=True).count()

	def active_projects(self):
		return self.projects.filter(active=True, account__active=True)

	def charging_staff_time(self):
		return StaffCharge.objects.filter(staff_member=self.id, end=None).exists()

	def get_staff_charge(self):
		try:
			return StaffCharge.objects.get(staff_member=self.id, end=None)
		except StaffCharge.DoesNotExist:
			return None

	class Meta:
		ordering = ['first_name']
		permissions = (
			("trigger_timed_services", "Can trigger timed services"),
			("use_billing_api", "Can use billing API"),
			("kiosk", "Kiosk services"),
		)

	def __str__(self):
		return self.get_full_name()


class Tool(models.Model):
	name = models.CharField(max_length=100, unique=True)
	parent_tool = models.ForeignKey('Tool', related_name="tool_children_set", null=True, blank=True, help_text='Select a parent tool to allow alternate usage', on_delete=models.CASCADE)
	visible = models.BooleanField(default=True, help_text="Specifies whether this tool is visible to users.")
	_category = models.CharField(db_column="category", null=True, blank=True, max_length=1000, help_text="Create sub-categories using slashes. For example \"Category 1/Sub-category 1\".")
	_operational = models.BooleanField(db_column="operational", default=False, help_text="Marking the tool non-operational will prevent users from using the tool.")
	_primary_owner = models.ForeignKey(User, db_column="primary_owner_id", null=True, blank=True, related_name="primary_tool_owner", help_text="The staff member who is responsible for administration of this tool.", on_delete=models.PROTECT)
	_backup_owners = models.ManyToManyField(User, db_table='NEMO_tool_backup_owners', blank=True, related_name="backup_for_tools", help_text="Alternate staff members who are responsible for administration of this tool when the primary owner is unavailable.")
	_location = models.CharField(db_column="location", null=True, blank=True, max_length=100)
	_phone_number = models.CharField(db_column="phone_number", null=True, blank=True, max_length=100)
	_notification_email_address = models.EmailField(db_column="notification_email_address", blank=True, null=True, help_text="Messages that relate to this tool (such as comments, problems, and shutdowns) will be forwarded to this email address. This can be a normal email address or a mailing list address.")
	_interlock = models.OneToOneField('Interlock', db_column="interlock_id", blank=True, null=True, on_delete=models.SET_NULL)
	# Policy fields:
	_requires_area_access = models.ForeignKey('Area', db_column="requires_area_access_id", null=True, blank=True, help_text="Indicates that this tool is physically located in a billable area and requires an active area access record in order to be operated.", on_delete=models.PROTECT)
	_grant_physical_access_level_upon_qualification = models.ForeignKey('PhysicalAccessLevel', db_column="grant_physical_access_level_upon_qualification_id", null=True, blank=True, help_text="The designated physical access level is granted to the user upon qualification for this tool.", on_delete=models.PROTECT)
	_grant_badge_reader_access_upon_qualification = models.CharField(db_column="grant_badge_reader_access_upon_qualification", max_length=100, null=True, blank=True, help_text="Badge reader access is granted to the user upon qualification for this tool.")
	_reservation_horizon = models.PositiveIntegerField(db_column="reservation_horizon", default=14, null=True, blank=True, help_text="Users may create reservations this many days in advance. Leave this field blank to indicate that no reservation horizon exists for this tool.")
	_minimum_usage_block_time = models.PositiveIntegerField(db_column="minimum_usage_block_time", null=True, blank=True, help_text="The minimum amount of time (in minutes) that a user must reserve this tool for a single reservation. Leave this field blank to indicate that no minimum usage block time exists for this tool.")
	_maximum_usage_block_time = models.PositiveIntegerField(db_column="maximum_usage_block_time", null=True, blank=True, help_text="The maximum amount of time (in minutes) that a user may reserve this tool for a single reservation. Leave this field blank to indicate that no maximum usage block time exists for this tool.")
	_maximum_reservations_per_day = models.PositiveIntegerField(db_column="maximum_reservations_per_day", null=True, blank=True, help_text="The maximum number of reservations a user may make per day for this tool.")
	_minimum_time_between_reservations = models.PositiveIntegerField(db_column="minimum_time_between_reservations", null=True, blank=True, help_text="The minimum amount of time (in minutes) that the same user must have between any two reservations for this tool.")
	_maximum_future_reservation_time = models.PositiveIntegerField(db_column="maximum_future_reservation_time", null=True, blank=True, help_text="The maximum amount of time (in minutes) that a user may reserve from the current time onwards.")
	_missed_reservation_threshold = models.PositiveIntegerField(db_column="missed_reservation_threshold", null=True, blank=True, help_text="The amount of time (in minutes) that a tool reservation may go unused before it is automatically marked as \"missed\" and hidden from the calendar. Usage can be from any user, regardless of who the reservation was originally created for. The cancellation process is triggered by a timed job on the web server.")
	_allow_delayed_logoff = models.BooleanField(db_column="allow_delayed_logoff", default=False, help_text='Upon logging off users may enter a delay before another user may use the tool. Some tools require "spin-down" or cleaning time after use.')
	_post_usage_questions = models.TextField(db_column="post_usage_questions", null=True, blank=True, help_text="")
	_policy_off_between_times = models.BooleanField(db_column="policy_off_between_times", default=False, help_text="Check this box to disable policy rules every day between the given times")
	_policy_off_start_time = models.TimeField(db_column="policy_off_start_time", null=True, blank=True, help_text="The start time when policy rules should NOT be enforced")
	_policy_off_end_time = models.TimeField(db_column="policy_off_end_time", null=True, blank=True, help_text="The end time when policy rules should NOT be enforced")
	_policy_off_weekend = models.BooleanField(db_column="policy_off_weekend", default=False, help_text="Whether or not policy rules should be enforced on weekends")

	class Meta:
		ordering = ['name']

	@property
	def category(self):
		return self.parent_tool.category if self.is_child_tool() else self._category

	@category.setter
	def category(self, value):
		self.raise_setter_error_if_child_tool("category")
		self._category = value

	@property
	def operational(self):
		return self.parent_tool.operational if self.is_child_tool() else self._operational

	@operational.setter
	def operational(self, value):
		self.raise_setter_error_if_child_tool("operational")
		self._operational = value

	@property
	def primary_owner(self):
		return self.parent_tool.primary_owner if self.is_child_tool() else self._primary_owner

	@primary_owner.setter
	def primary_owner(self, value):
		self.raise_setter_error_if_child_tool("primary_owner")
		self._primary_owner = value

	@property
	def backup_owners(self):
		return self.parent_tool.backup_owners if self.is_child_tool() else self._backup_owners

	@backup_owners.setter
	def backup_owners(self, value):
		self.raise_setter_error_if_child_tool("backup_owners")
		self._backup_owners = value

	@property
	def location(self):
		return self.parent_tool.location if self.is_child_tool() else self._location

	@location.setter
	def location(self, value):
		self.raise_setter_error_if_child_tool("location")
		self._location = value

	@property
	def phone_number(self):
		return self.parent_tool.phone_number if self.is_child_tool() else self._phone_number

	@phone_number.setter
	def phone_number(self, value):
		self.raise_setter_error_if_child_tool("phone_number")
		self._phone_number = value

	@property
	def notification_email_address(self):
		return self.parent_tool.notification_email_address if self.is_child_tool() else self._notification_email_address

	@notification_email_address.setter
	def notification_email_address(self, value):
		self.raise_setter_error_if_child_tool("notification_email_address")
		self._notification_email_address = value

	@property
	def interlock(self):
		return self.parent_tool.interlock if self.is_child_tool() else self._interlock

	@interlock.setter
	def interlock(self, value):
		self.raise_setter_error_if_child_tool("interlock")
		self._interlock = value

	@property
	def requires_area_access(self):
		return self.parent_tool.requires_area_access if self.is_child_tool() else self._requires_area_access

	@requires_area_access.setter
	def requires_area_access(self, value):
		self.raise_setter_error_if_child_tool("requires_area_access")
		self._requires_area_access = value

	@property
	def grant_physical_access_level_upon_qualification(self):
		return self.parent_tool.grant_physical_access_level_upon_qualification if self.is_child_tool() else self._grant_physical_access_level_upon_qualification

	@grant_physical_access_level_upon_qualification.setter
	def grant_physical_access_level_upon_qualification(self, value):
		self.raise_setter_error_if_child_tool("grant_physical_access_level_upon_qualification")
		self._grant_physical_access_level_upon_qualification = value

	@property
	def grant_badge_reader_access_upon_qualification(self):
		return self.parent_tool.grant_badge_reader_access_upon_qualification if self.is_child_tool() else self._grant_badge_reader_access_upon_qualification

	@grant_badge_reader_access_upon_qualification.setter
	def grant_badge_reader_access_upon_qualification(self, value):
		self.raise_setter_error_if_child_tool("grant_badge_reader_access_upon_qualification")
		self._grant_badge_reader_access_upon_qualification = value

	@property
	def reservation_horizon(self):
		return self.parent_tool.reservation_horizon if self.is_child_tool() else self._reservation_horizon

	@reservation_horizon.setter
	def reservation_horizon(self, value):
		self.raise_setter_error_if_child_tool("reservation_horizon")
		self._reservation_horizon = value

	@property
	def minimum_usage_block_time(self):
		return self.parent_tool.minimum_usage_block_time if self.is_child_tool() else self._minimum_usage_block_time

	@minimum_usage_block_time.setter
	def minimum_usage_block_time(self, value):
		self.raise_setter_error_if_child_tool("minimum_usage_block_time")
		self._minimum_usage_block_time = value

	@property
	def maximum_usage_block_time(self):
		return self.parent_tool.maximum_usage_block_time if self.is_child_tool() else self._maximum_usage_block_time

	@maximum_usage_block_time.setter
	def maximum_usage_block_time(self, value):
		self.raise_setter_error_if_child_tool("maximum_usage_block_time")
		self._maximum_usage_block_time = value

	@property
	def maximum_reservations_per_day(self):
		return self.parent_tool.maximum_reservations_per_day if self.is_child_tool() else self._maximum_reservations_per_day

	@maximum_reservations_per_day.setter
	def maximum_reservations_per_day(self, value):
		self.raise_setter_error_if_child_tool("maximum_reservations_per_day")
		self._maximum_reservations_per_day = value

	@property
	def minimum_time_between_reservations(self):
		return self.parent_tool.minimum_time_between_reservations if self.is_child_tool() else self._minimum_time_between_reservations

	@minimum_time_between_reservations.setter
	def minimum_time_between_reservations(self, value):
		self.raise_setter_error_if_child_tool("minimum_time_between_reservations")
		self._minimum_time_between_reservations = value

	@property
	def maximum_future_reservation_time(self):
		return self.parent_tool.maximum_future_reservation_time if self.is_child_tool() else self._maximum_future_reservation_time

	@maximum_future_reservation_time.setter
	def maximum_future_reservation_time(self, value):
		self.raise_setter_error_if_child_tool("maximum_future_reservation_time")
		self._maximum_future_reservation_time = value

	@property
	def missed_reservation_threshold(self):
		return self.parent_tool.missed_reservation_threshold if self.is_child_tool() else self._missed_reservation_threshold

	@missed_reservation_threshold.setter
	def missed_reservation_threshold(self, value):
		self.raise_setter_error_if_child_tool("missed_reservation_threshold")
		self._missed_reservation_threshold = value

	@property
	def allow_delayed_logoff(self):
		return self.parent_tool.allow_delayed_logoff if self.is_child_tool() else self._allow_delayed_logoff

	@allow_delayed_logoff.setter
	def allow_delayed_logoff(self, value):
		self.raise_setter_error_if_child_tool("allow_delayed_logoff")
		self._allow_delayed_logoff = value

	@property
	def post_usage_questions(self):
		return self.parent_tool.post_usage_questions if self.is_child_tool() else self._post_usage_questions

	@post_usage_questions.setter
	def post_usage_questions(self, value):
		self.raise_setter_error_if_child_tool("post_usage_questions")
		self._post_usage_questions = value

	@property
	def policy_off_between_times(self):
		return self.parent_tool.policy_off_between_times if self.is_child_tool() else self._policy_off_between_times

	@policy_off_between_times.setter
	def policy_off_between_times(self, value):
		self.raise_setter_error_if_child_tool("policy_off_between_times")
		self._policy_off_between_times = value

	@property
	def policy_off_start_time(self):
		return self.parent_tool.policy_off_start_time if self.is_child_tool() else self._policy_off_start_time

	@policy_off_start_time.setter
	def policy_off_start_time(self, value):
		self.raise_setter_error_if_child_tool("policy_off_start_time")
		self._policy_off_start_time = value

	@property
	def policy_off_end_time(self):
		return self.parent_tool.policy_off_end_time if self.is_child_tool() else self._policy_off_end_time

	@policy_off_end_time.setter
	def policy_off_end_time(self, value):
		self.raise_setter_error_if_child_tool("policy_off_end_time")
		self._policy_off_end_time = value

	@property
	def policy_off_weekend(self):
		return self.parent_tool.policy_off_weekend if self.is_child_tool() else self._policy_off_weekend

	@policy_off_weekend.setter
	def policy_off_weekend(self, value):
		self.raise_setter_error_if_child_tool("policy_off_weekend")
		self._policy_off_weekend = value

	def name_or_child_in_use_name(self) -> str:
		""" this method returns the tool name unless one of its children is in use """
		if self.in_use():
			return self.get_current_usage_event().tool.name
		return self.name

	def is_child_tool(self):
		return self.parent_tool != None

	def is_parent_tool(self):
		return self.tool_children_set.all().exists()

	def tool_or_parent_id(self):
		""" This method returns the tool id or the parent tool id if tool is a child """
		if self.is_child_tool():
			return self.parent_tool.id
		else:
			return self.id

	def get_family_tool_ids(self):
		""" this method returns a list of children tool ids, parent and self id """
		tool_ids = [child_tool.id for child_tool in self.tool_children_set.all()]
		# parent tool
		if self.is_child_tool():
			tool_ids.append(self.parent_tool.id)
		# self
		tool_ids.append(self.id)
		return tool_ids

	def raise_setter_error_if_child_tool(self, field):
		if self.is_child_tool():
			raise AttributeError(f"Cannot set property {field} on a child/alternate tool")

	def __str__(self):
		return self.name

	def get_absolute_url(self):
		from django.urls import reverse
		return reverse('tool_control', args=[self.tool_or_parent_id()])

	def name_display(self):
		return f"{self.name} ({self.parent_tool.name})" if self.is_child_tool() else f"{self.name}"
	name_display.admin_order_field = '_name'
	name_display.short_description = 'Name'

	def operational_display(self):
		return self.operational
	operational_display.admin_order_field = '_operational'
	operational_display.boolean = True
	operational_display.short_description = 'Operational'

	def problematic(self):
		return self.parent_tool.task_set.filter(resolved=False, cancelled=False).exists() if self.is_child_tool() else self.task_set.filter(resolved=False, cancelled=False).exists()
	problematic.admin_order_field = 'task'
	problematic.boolean = True

	def problems(self):
		return self.parent_tool.task_set.filter(resolved=False, cancelled=False) if self.is_child_tool() else self.task_set.filter(resolved=False, cancelled=False)

	def comments(self):
		unexpired = Q(expiration_date__isnull=True) | Q(expiration_date__gt=timezone.now())
		return self.parent_tool.comment_set.filter(visible=True).filter(unexpired) if self.is_child_tool() else self.comment_set.filter(visible=True).filter(unexpired)

	def required_resource_is_unavailable(self):
		return self.parent_tool.required_resource_set.filter(available=False).exists() if self.is_child_tool() else self.required_resource_set.filter(available=False).exists()

	def nonrequired_resource_is_unavailable(self):
		return self.parent_tool.nonrequired_resource_set.filter(available=False).exists() if self.is_child_tool() else self.nonrequired_resource_set.filter(available=False).exists()

	def all_resources_available(self):
		required_resources_available = not self.unavailable_required_resources().exists()
		nonrequired_resources_available = not self.unavailable_nonrequired_resources().exists()
		if required_resources_available and nonrequired_resources_available:
			return True
		return False

	def unavailable_required_resources(self):
		return self.parent_tool.required_resource_set.filter(available=False) if self.is_child_tool() else self.required_resource_set.filter(available=False)

	def unavailable_nonrequired_resources(self):
		return self.parent_tool.nonrequired_resource_set.filter(available=False) if self.is_child_tool() else self.nonrequired_resource_set.filter(available=False)

	def in_use(self):
		result = UsageEvent.objects.filter(tool_id__in=self.get_family_tool_ids(), end=None).exists()
		return result

	def delayed_logoff_in_progress(self):
		result = UsageEvent.objects.filter(tool_id__in=self.get_family_tool_ids(), end__gt=timezone.now()).exists()
		return result

	def get_delayed_logoff_usage_event(self):
		try:
			return UsageEvent.objects.get(tool_id__in=self.get_family_tool_ids(), end__gt=timezone.now())
		except UsageEvent.DoesNotExist:
			return None

	def scheduled_outages(self):
		""" Returns a QuerySet of scheduled outages that are in progress for this tool. This includes tool outages, and resources outages (when the tool fully depends on the resource). """
		return ScheduledOutage.objects.filter(Q(tool=self.tool_or_parent_id()) | Q(resource__fully_dependent_tools__in=[self.tool_or_parent_id()]), start__lte=timezone.now(), end__gt=timezone.now())

	def scheduled_outage_in_progress(self):
		""" Returns a true if a tool or resource outage is currently in effect for this tool. Otherwise, returns false. """
		return ScheduledOutage.objects.filter(Q(tool=self.tool_or_parent_id()) | Q(resource__fully_dependent_tools__in=[self.tool_or_parent_id()]), start__lte=timezone.now(), end__gt=timezone.now()).exists()

	def is_configurable(self):
		return self.parent_tool.configuration_set.exists() if self.is_child_tool() else self.configuration_set.exists()
	is_configurable.admin_order_field = 'configuration'
	is_configurable.boolean = True
	is_configurable.short_description = 'Configurable'

	def get_configuration_information(self, user, start):
		configurations = self.parent_tool.configuration_set.all().order_by('display_priority') if self.is_child_tool() else self.configuration_set.all().order_by('display_priority')
		notice_limit = 0
		able_to_self_configure = True
		for config in configurations:
			notice_limit = max(notice_limit, config.advance_notice_limit)
			# If an item is already excluded from the configuration agenda or the user is not a qualified maintainer, then tool self-configuration is not possible.
			if config.exclude_from_configuration_agenda or not config.user_is_maintainer(user):
				able_to_self_configure = False
		results = {
			'configurations': configurations,
			'notice_limit': notice_limit,
			'able_to_self_configure': able_to_self_configure,
			'additional_information_maximum_length': ADDITIONAL_INFORMATION_MAXIMUM_LENGTH,
		}
		if start:
			results['sufficient_notice'] = (start - timedelta(hours=notice_limit) >= timezone.now())
		return results

	def configuration_widget(self, user):
		config_input = {
			'configurations': self.parent_tool.configuration_set.all().order_by('display_priority') if self.is_child_tool() else self.configuration_set.all().order_by('display_priority'),
			'user': user
		}
		configurations = ConfigurationEditor()
		return configurations.render(None, config_input)

	def get_current_usage_event(self):
		""" Gets the usage event for the current user of this tool. """
		try:
			return UsageEvent.objects.get(end=None, tool_id__in=self.get_family_tool_ids())
		except UsageEvent.DoesNotExist:
			return None

	def should_enforce_policy(self, reservation):
		""" Returns whether or not the policy rules should be enforced. """
		should_enforce = True

		start_time = reservation.start.astimezone(timezone.get_current_timezone())
		end_time = reservation.end.astimezone(timezone.get_current_timezone())
		if self.policy_off_weekend and start_time.weekday() >= 5 and end_time.weekday() >= 5:
			should_enforce = False
		if self.policy_off_between_times and self.policy_off_start_time and self.policy_off_end_time:
			if self.policy_off_start_time <= self.policy_off_end_time:
				""" Range something like 6am-6pm """
				if self.policy_off_start_time <= start_time.time() <= self.policy_off_end_time and self.policy_off_start_time <= end_time.time() <= self.policy_off_end_time:
					should_enforce = False
			else:
				""" Range something like 6pm-6am """
				if (self.policy_off_start_time <= start_time.time() or start_time.time() <= self.policy_off_end_time) and (self.policy_off_start_time <= end_time.time() or end_time.time() <= self.policy_off_end_time):
					should_enforce = False
		return should_enforce


class Configuration(models.Model):
	tool = models.ForeignKey(Tool, help_text="The tool that this configuration option applies to.", on_delete=models.CASCADE)
	name = models.CharField(max_length=200, help_text="The name of this overall configuration. This text is displayed as a label on the tool control page.")
	configurable_item_name = models.CharField(blank=True, null=True, max_length=200, help_text="The name of the tool part being configured. This text is displayed as a label on the tool control page. Leave this field blank if there is only one configuration slot.")
	advance_notice_limit = models.PositiveIntegerField(help_text="Configuration changes must be made this many hours in advance.")
	display_priority = models.PositiveIntegerField(help_text="The order in which this configuration will be displayed beside others when making a reservation and controlling a tool. Can be any positive integer including 0. Lower values are displayed first.")
	prompt = models.TextField(blank=True, null=True, help_text="The textual description the user will see when making a configuration choice.")
	current_settings = models.TextField(blank=True, null=True, help_text="The current configuration settings for a tool. Multiple values are separated by commas.")
	available_settings = models.TextField(blank=True, null=True, help_text="The available choices to select for this configuration option. Multiple values are separated by commas.")
	maintainers = models.ManyToManyField(User, blank=True, help_text="Select the users that are allowed to change this configuration.")
	qualified_users_are_maintainers = models.BooleanField(default=False, help_text="Any user that is qualified to use the tool that this configuration applies to may also change this configuration. Checking this box implicitly adds qualified users to the maintainers list.")
	exclude_from_configuration_agenda = models.BooleanField(default=False, help_text="Reservations containing this configuration will be excluded from the NanoFab technician's Configuration Agenda page.")
	absence_string = models.CharField(max_length=100, blank=True, null=True, help_text="The text that appears to indicate absence of a choice.")

	def get_current_setting(self, slot):
		if slot < 0:
			raise IndexError("Slot index of " + str(slot) + " is out of bounds for configuration \"" + self.name + "\" (id = " + str(self.id) + ").")
		return self.current_settings_as_list()[slot]

	def current_settings_as_list(self):
		return [x.strip() for x in self.current_settings.split(',')]

	def available_settings_as_list(self):
		return [x.strip() for x in self.available_settings.split(',')]

	def get_available_setting(self, choice):
		choice = int(choice)
		available_settings = self.available_settings_as_list()
		return available_settings[choice]

	def replace_current_setting(self, slot, choice):
		slot = int(slot)
		current_settings = self.current_settings_as_list()
		current_settings[slot] = self.get_available_setting(choice)
		self.current_settings = ', '.join(current_settings)

	def range_of_configurable_items(self):
		return range(0, len(self.current_settings.split(',')))

	def user_is_maintainer(self, user):
		if user in self.maintainers.all() or user.is_staff:
			return True
		if self.qualified_users_are_maintainers and (user in self.tool.user_set.all() or user.is_staff):
			return True
		return False

	class Meta:
		ordering = ['tool', 'name']

	def __str__(self):
		return str(self.tool.name) + ': ' + str(self.name)


class TrainingSession(models.Model):
	class Type(object):
		INDIVIDUAL = 0
		GROUP = 1
		Choices = (
			(INDIVIDUAL, 'Individual'),
			(GROUP, 'Group')
		)

	trainer = models.ForeignKey(User, related_name="teacher_set", on_delete=models.CASCADE)
	trainee = models.ForeignKey(User, related_name="student_set", on_delete=models.CASCADE)
	tool = models.ForeignKey(Tool, on_delete=models.CASCADE)
	project = models.ForeignKey('Project', on_delete=models.CASCADE)
	duration = models.PositiveIntegerField(help_text="The duration of the training session in minutes.")
	type = models.IntegerField(choices=Type.Choices)
	date = models.DateTimeField(default=timezone.now)
	qualified = models.BooleanField(default=False, help_text="Indicates that after this training session the user was qualified to use the tool.")

	class Meta:
		ordering = ['-date']

	def __str__(self):
		return str(self.id)


class StaffCharge(CalendarDisplay):
	staff_member = models.ForeignKey(User, related_name='staff_charge_actor', on_delete=models.CASCADE)
	customer = models.ForeignKey(User, related_name='staff_charge_customer', on_delete=models.CASCADE)
	project = models.ForeignKey('Project', on_delete=models.CASCADE)
	start = models.DateTimeField(default=timezone.now)
	end = models.DateTimeField(null=True, blank=True)
	validated = models.BooleanField(default=False)

	class Meta:
		ordering = ['-start']

	def __str__(self):
		return str(self.id)


class Area(models.Model):
	name = models.CharField(max_length=200, help_text='What is the name of this area? The name will be displayed on the tablet login and logout pages.')
	welcome_message = models.TextField(help_text='The welcome message will be displayed on the tablet login page. You can use HTML and JavaScript.')

	class Meta:
		ordering = ['name']

	def __str__(self):
		return self.name


class AreaAccessRecord(CalendarDisplay):
	area = models.ForeignKey(Area, on_delete=models.CASCADE)
	customer = models.ForeignKey(User, on_delete=models.CASCADE)
	project = models.ForeignKey('Project', on_delete=models.CASCADE)
	start = models.DateTimeField(default=timezone.now)
	end = models.DateTimeField(null=True, blank=True)
	staff_charge = models.ForeignKey(StaffCharge, blank=True, null=True, on_delete=models.CASCADE)

	class Meta:
		ordering = ['-start']

	def __str__(self):
		return str(self.id)


class ConfigurationHistory(models.Model):
	configuration = models.ForeignKey(Configuration, on_delete=models.CASCADE)
	user = models.ForeignKey(User, on_delete=models.CASCADE)
	modification_time = models.DateTimeField(default=timezone.now)
	slot = models.PositiveIntegerField()
	setting = models.TextField()

	class Meta:
		ordering = ['-modification_time']
		verbose_name_plural = "Configuration histories"

	def __str__(self):
		return str(self.id)


class Account(models.Model):
	name = models.CharField(max_length=100, unique=True)
	active = models.BooleanField(default=True, help_text="Users may only charge to an account if it is active. Deactivate the account to block future billable activity (such as tool usage and consumable check-outs) of all the projects that belong to it.")

	class Meta:
		ordering = ['name']

	def __str__(self):
		return str(self.name)


class Project(models.Model):
	name = models.CharField(max_length=100, unique=True)
	application_identifier = models.CharField(max_length=100)
	account = models.ForeignKey(Account, help_text="All charges for this project will be billed to the selected account.", on_delete=models.CASCADE)
	active = models.BooleanField(default=True, help_text="Users may only charge to a project if it is active. Deactivate the project to block billable activity (such as tool usage and consumable check-outs).")

	class Meta:
		ordering = ['name']

	def __str__(self):
		return str(self.name)


def pre_delete_entity(sender, instance, using, **kwargs):
	""" Remove activity history and membership history when an account, project, tool, or user is deleted. """
	content_type = ContentType.objects.get_for_model(sender)
	ActivityHistory.objects.filter(object_id=instance.id, content_type=content_type).delete()
	MembershipHistory.objects.filter(parent_object_id=instance.id, parent_content_type=content_type).delete()
	MembershipHistory.objects.filter(child_object_id=instance.id, child_content_type=content_type).delete()


# Call the function "pre_delete_entity" every time an account, project, tool, or user is deleted:
pre_delete.connect(pre_delete_entity, sender=Account)
pre_delete.connect(pre_delete_entity, sender=Project)
pre_delete.connect(pre_delete_entity, sender=Tool)
pre_delete.connect(pre_delete_entity, sender=User)


class Reservation(CalendarDisplay):
	user = models.ForeignKey(User, related_name="reservation_user", on_delete=models.CASCADE)
	creator = models.ForeignKey(User, related_name="reservation_creator", on_delete=models.CASCADE)
	creation_time = models.DateTimeField(default=timezone.now)
	tool = models.ForeignKey(Tool, on_delete=models.CASCADE)
	project = models.ForeignKey(Project, null=True, blank=True, help_text="Indicates the intended project for this reservation. A missed reservation would be billed to this project.", on_delete=models.CASCADE)
	start = models.DateTimeField('start')
	end = models.DateTimeField('end')
	short_notice = models.BooleanField(default=None, help_text="Indicates that the reservation was made after the configuration deadline for a tool. NanoFab staff may not have enough time to properly configure the tool before the user is scheduled to use it.")
	cancelled = models.BooleanField(default=False, help_text="Indicates that the reservation has been cancelled, moved, or resized.")
	cancellation_time = models.DateTimeField(null=True, blank=True)
	cancelled_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
	missed = models.BooleanField(default=False, help_text="Indicates that the tool was not enabled by anyone before the tool's \"missed reservation threshold\" passed.")
	shortened = models.BooleanField(default=False, help_text="Indicates that the user finished using the tool and relinquished the remaining time on their reservation. The reservation will no longer be visible on the calendar and a descendant reservation will be created in place of the existing one.")
	descendant = models.OneToOneField('Reservation', related_name='ancestor', null=True, blank=True, on_delete=models.SET_NULL, help_text="Any time a reservation is moved or resized, the old reservation is cancelled and a new reservation with updated information takes its place. This field links the old reservation to the new one, so the history of reservation moves & changes can be easily tracked.")
	additional_information = models.TextField(null=True, blank=True)
	self_configuration = models.BooleanField(default=False, help_text="When checked, indicates that the user will perform their own tool configuration (instead of requesting that the NanoFab staff configure it for them).")
	title = models.TextField(default='', blank=True, max_length=200, help_text="Shows a custom title for this reservation on the calendar. Leave this field blank to display the reservation's user name as the title (which is the default behaviour).")

	def duration(self):
		return self.end - self.start

	def has_not_ended(self):
		return False if self.end < timezone.now() else True

	def save_and_notify(self):
		self.save()
		from NEMO.views.calendar import send_user_cancelled_reservation_notification, send_user_created_reservation_notification
		if self.cancelled:
			send_user_cancelled_reservation_notification(self)
		else:
			send_user_created_reservation_notification(self)

	class Meta:
		ordering = ['-start']

	def __str__(self):
		return str(self.id)


class UsageEvent(CalendarDisplay):
	user = models.ForeignKey(User, related_name="usage_event_user", on_delete=models.CASCADE)
	operator = models.ForeignKey(User, related_name="usage_event_operator", on_delete=models.CASCADE)
	project = models.ForeignKey(Project, on_delete=models.CASCADE)
	tool = models.ForeignKey(Tool, related_name='+', on_delete=models.CASCADE)  # The related_name='+' disallows reverse lookups. Helper functions of other models should be used instead.
	start = models.DateTimeField(default=timezone.now)
	end = models.DateTimeField(null=True, blank=True)
	validated = models.BooleanField(default=False)
	run_data = models.TextField(null=True, blank=True)

	def duration(self):
		return calculate_duration(self.start, self.end, "In progress")

	class Meta:
		ordering = ['-start']

	def __str__(self):
		return str(self.id)


class Consumable(models.Model):
	name = models.CharField(max_length=100)
	category = models.ForeignKey('ConsumableCategory', blank=True, null=True, on_delete=models.CASCADE)
	quantity = models.IntegerField(help_text="The number of items currently in stock.")
	visible = models.BooleanField(default=True)
	reminder_threshold = models.IntegerField(help_text="More of this item should be ordered when the quantity falls below this threshold.")
	reminder_email = models.EmailField(help_text="An email will be sent to this address when the quantity of this item falls below the reminder threshold.")

	class Meta:
		ordering = ['name']

	def __str__(self):
		return self.name


class ConsumableCategory(models.Model):
	name = models.CharField(max_length=100)

	class Meta:
		ordering = ['name']
		verbose_name_plural = 'Consumable categories'

	def __str__(self):
		return self.name


class ConsumableWithdraw(models.Model):
	customer = models.ForeignKey(User, related_name="consumable_user", help_text="The user who will use the consumable item.", on_delete=models.CASCADE)
	merchant = models.ForeignKey(User, related_name="consumable_merchant", help_text="The staff member that performed the withdraw.", on_delete=models.CASCADE)
	consumable = models.ForeignKey(Consumable, on_delete=models.CASCADE)
	quantity = models.PositiveIntegerField()
	project = models.ForeignKey(Project, help_text="The withdraw will be billed to this project.", on_delete=models.CASCADE)
	date = models.DateTimeField(default=timezone.now, help_text="The date and time when the user withdrew the consumable.")

	class Meta:
		ordering = ['-date']

	def __str__(self):
		return str(self.id)


class InterlockCard(models.Model):
	server = models.CharField(max_length=100)
	port = models.PositiveIntegerField()
	number = models.PositiveIntegerField(blank=True, null=True)
	even_port = models.PositiveIntegerField(blank=True, null=True)
	odd_port = models.PositiveIntegerField(blank=True, null=True)
	category = models.ForeignKey('InterlockCardCategory', blank=False, null=False, on_delete=models.CASCADE, default=1)
	username = models.CharField(max_length=100, blank=True, null=True)
	password = models.CharField(max_length=100, blank=True, null=True)
	enabled = models.BooleanField(blank=False, null=False, default=True)

	class Meta:
		ordering = ['server', 'number']

	def __str__(self):
		return str(self.server) + (', card ' + str(self.number) if self.number else '')


class Interlock(models.Model):
	class State(object):
		UNKNOWN = -1
		# The numeric command types for the interlock hardware:
		UNLOCKED = 1
		LOCKED = 2
		Choices = (
			(UNKNOWN, 'Unknown'),
			(UNLOCKED, 'Unlocked'),  # The 'unlocked' and 'locked' constants match the hardware command types to control the interlocks.
			(LOCKED, 'Locked'),
		)

	card = models.ForeignKey(InterlockCard, on_delete=models.CASCADE)
	channel = models.PositiveIntegerField(blank=True, null=True, verbose_name="Channel/Relay")
	state = models.IntegerField(choices=State.Choices, default=State.UNKNOWN)
	most_recent_reply = models.TextField(default="None")

	def unlock(self):
		from NEMO import interlocks
		return interlocks.get(self.card.category).unlock(self)

	def lock(self):
		from NEMO import interlocks
		return interlocks.get(self.card.category).lock(self)

	class Meta:
		unique_together = ('card', 'channel')
		ordering = ['card__server', 'card__number', 'channel']

	def __str__(self):
		return str(self.card) + ", channel " + str(self.channel)


class InterlockCardCategory(models.Model):
	name = models.CharField(max_length=200, help_text="The name for this interlock category")
	key = models.CharField(max_length=100, help_text="The key to identify this interlock category by in interlocks.py")

	class Meta:
		verbose_name_plural = 'Interlock card categories'
		ordering = ['name']

	def __str__(self):
		return str(self.name)


class Task(models.Model):
	class Urgency(object):
		LOW = -1
		NORMAL = 0
		HIGH = 1
		Choices = (
			(LOW, 'Low'),
			(NORMAL, 'Normal'),
			(HIGH, 'High'),
		)
	urgency = models.IntegerField(choices=Urgency.Choices)
	tool = models.ForeignKey(Tool, help_text="The tool that this task relates to.", on_delete=models.CASCADE)
	force_shutdown = models.BooleanField(default=None, help_text="Indicates that the tool this task relates to will be shutdown until the task is resolved.")
	safety_hazard = models.BooleanField(default=None, help_text="Indicates that this task represents a safety hazard to the NanoFab.")
	creator = models.ForeignKey(User, related_name="created_tasks", help_text="The user who created the task.", on_delete=models.CASCADE)
	creation_time = models.DateTimeField(default=timezone.now, help_text="The date and time when the task was created.")
	problem_category = models.ForeignKey('TaskCategory', null=True, blank=True, related_name='problem_category', on_delete=models.SET_NULL)
	problem_description = models.TextField(blank=True, null=True)
	progress_description = models.TextField(blank=True, null=True)
	last_updated = models.DateTimeField(null=True, blank=True, help_text="The last time this task was modified. (Creating the task does not count as modifying it.)")
	last_updated_by = models.ForeignKey(User, null=True, blank=True, help_text="The last user who modified this task. This should always be a staff member.", on_delete=models.SET_NULL)
	estimated_resolution_time = models.DateTimeField(null=True, blank=True, help_text="The estimated date and time that the task will be resolved.")
	cancelled = models.BooleanField(default=False)
	resolved = models.BooleanField(default=False)
	resolution_time = models.DateTimeField(null=True, blank=True, help_text="The timestamp of when the task was marked complete or cancelled.")
	resolver = models.ForeignKey(User, null=True, blank=True, related_name='task_resolver', help_text="The staff member who resolved the task.", on_delete=models.SET_NULL)
	resolution_description = models.TextField(blank=True, null=True)
	resolution_category = models.ForeignKey('TaskCategory', null=True, blank=True, related_name='resolution_category', on_delete=models.SET_NULL)

	class Meta:
		ordering = ['-creation_time']

	def __str__(self):
		return str(self.id)

	def current_status(self):
		""" Returns the textual description of the current task status """
		try:
			return TaskHistory.objects.filter(task_id=self.id).latest().status
		except TaskHistory.DoesNotExist:
			return None

	def task_images(self):
		return TaskImages.objects.filter(task=self).order_by()


class TaskImages(models.Model):
	task = models.ForeignKey(Task, on_delete=models.CASCADE)
	image = models.ImageField(upload_to=get_task_image_filename, verbose_name='Image')
	uploaded_at = models.DateTimeField(auto_now_add=True)

	def filename(self):
		return os.path.basename(self.image.name)

	class Meta:
		verbose_name_plural = "Task images"
		ordering = ['-uploaded_at']


# These two auto-delete task images from filesystem when they are unneeded:
@receiver(models.signals.post_delete, sender=TaskImages)
def auto_delete_file_on_delete(sender, instance: TaskImages, **kwargs):
	"""	Deletes file from filesystem when corresponding `TaskImages` object is deleted.	"""
	if instance.image:
		if os.path.isfile(instance.image.path):
			os.remove(instance.image.path)


@receiver(models.signals.pre_save, sender=TaskImages)
def auto_delete_file_on_change(sender, instance: TaskImages, **kwargs):
	"""	Deletes old file from filesystem when corresponding `TaskImages` object is updated with new file. """
	if not instance.pk:
		return False

	try:
		old_file = TaskImages.objects.get(pk=instance.pk).image
	except TaskImages.DoesNotExist:
		return False

	new_file = instance.image
	if not old_file == new_file:
		if os.path.isfile(old_file.path):
			os.remove(old_file.path)


class TaskCategory(models.Model):
	class Stage(object):
		INITIAL_ASSESSMENT = 0
		COMPLETION = 1
		Choices = (
			(INITIAL_ASSESSMENT, 'Initial assessment'),
			(COMPLETION, 'Completion'),
		)
	name = models.CharField(max_length=100)
	stage = models.IntegerField(choices=Stage.Choices)

	class Meta:
		verbose_name_plural = "Task categories"
		ordering = ['name']

	def __str__(self):
		return str(self.name)


class TaskStatus(models.Model):
	name = models.CharField(max_length=200, unique=True)
	notify_primary_tool_owner = models.BooleanField(default=False, help_text="Notify the primary tool owner when a task transitions to this status")
	notify_backup_tool_owners = models.BooleanField(default=False, help_text="Notify the backup tool owners when a task transitions to this status")
	notify_tool_notification_email = models.BooleanField(default=False, help_text="Send an email to the tool notification email address when a task transitions to this status")
	custom_notification_email_address = models.EmailField(blank=True, help_text="Notify a custom email address when a task transitions to this status. Leave this blank if you don't need it.")
	notification_message = models.TextField(blank=True)

	def __str__(self):
		return self.name

	class Meta:
		verbose_name_plural = 'task statuses'
		ordering = ['name']


class TaskHistory(models.Model):
	task = models.ForeignKey(Task, help_text='The task that this historical entry refers to', related_name='history', on_delete=models.CASCADE)
	status = models.CharField(max_length=200, help_text="A text description of the task's status")
	time = models.DateTimeField(auto_now_add=True, help_text='The date and time when the task status was changed')
	user = models.ForeignKey(User, help_text='The user that changed the task to this status', on_delete=models.CASCADE)

	class Meta:
		verbose_name_plural = 'task histories'
		ordering = ['time']
		get_latest_by = 'time'


class Comment(models.Model):
	tool = models.ForeignKey(Tool, help_text="The tool that this comment relates to.", on_delete=models.CASCADE)
	author = models.ForeignKey(User, on_delete=models.CASCADE)
	creation_date = models.DateTimeField(default=timezone.now)
	expiration_date = models.DateTimeField(blank=True, null=True, help_text="The comment will only be visible until this date.")
	visible = models.BooleanField(default=True)
	hide_date = models.DateTimeField(blank=True, null=True, help_text="The date when this comment was hidden. If it is still visible or has expired then this date should be empty.")
	hidden_by = models.ForeignKey(User, null=True, blank=True, related_name="hidden_comments", on_delete=models.SET_NULL)
	content = models.TextField()

	class Meta:
		ordering = ['-creation_date']

	def __str__(self):
		return str(self.id)


class ResourceCategory(models.Model):
	name = models.CharField(max_length=200)

	def __str__(self):
		return str(self.name)

	class Meta:
		verbose_name_plural = 'resource categories'
		ordering = ['name']


class Resource(models.Model):
	name = models.CharField(max_length=200)
	category = models.ForeignKey(ResourceCategory, blank=True, null=True, on_delete=models.SET_NULL)
	available = models.BooleanField(default=True, help_text="Indicates whether the resource is available to be used.")
	fully_dependent_tools = models.ManyToManyField(Tool, blank=True, related_name="required_resource_set", help_text="These tools will be completely inoperable if the resource is unavailable.")
	partially_dependent_tools = models.ManyToManyField(Tool, blank=True, related_name="nonrequired_resource_set", help_text="These tools depend on this resource but can operated at a reduced capacity if the resource is unavailable.")
	dependent_areas = models.ManyToManyField(Area, blank=True, related_name="required_resources", help_text="Users will not be able to login to these areas when the resource is unavailable.")
	restriction_message = models.TextField(blank=True, help_text="The message that is displayed to users on the tool control page when this resource is unavailable.")

	class Meta:
		ordering = ['name']

	def __str__(self):
		return self.name


class ActivityHistory(models.Model):
	"""
	Stores the history of when accounts, projects, and users are active.
	This class uses generic relations in order to point to any model type.
	For more information see: https://docs.djangoproject.com/en/dev/ref/contrib/contenttypes/#generic-relations
	"""

	class Action(object):
		ACTIVATED = True
		DEACTIVATED = False
		Choices = (
			(ACTIVATED, 'Activated'),
			(DEACTIVATED, 'Deactivated'),
		)

	content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
	object_id = models.PositiveIntegerField()
	content_object = GenericForeignKey('content_type', 'object_id')
	action = models.BooleanField(choices=Action.Choices, default=None, help_text="The target state (activated or deactivated).")
	date = models.DateTimeField(default=timezone.now, help_text="The time at which the active state was changed.")
	authorizer = models.ForeignKey(User, help_text="The staff member who changed the active state of the account, project, or user in question.", on_delete=models.CASCADE)

	class Meta:
		ordering = ['-date']
		verbose_name_plural = 'activity histories'

	def __str__(self):
		if self.action:
			state = "activated"
		else:
			state = "deactivated"
		return str(self.content_type).capitalize() + " " + str(self.object_id) + " " + state


class MembershipHistory(models.Model):
	"""
	Stores the history of membership between related items. For example, users can be members of projects.
	Likewise, projects can belong to accounts. This class uses generic relations in order to point to any model type.
	For more information see: https://docs.djangoproject.com/en/dev/ref/contrib/contenttypes/#generic-relations
	"""

	class Action(object):
		ADDED = True
		REMOVED = False
		Choices = (
			(ADDED, 'Added'),
			(REMOVED, 'Removed'),
		)

	# The parent entity can be either an account or project.
	parent_content_type = models.ForeignKey(ContentType, related_name="parent_content_type", on_delete=models.CASCADE)
	parent_object_id = models.PositiveIntegerField()
	parent_content_object = GenericForeignKey('parent_content_type', 'parent_object_id')

	# The child entity can be either a project or user.
	child_content_type = models.ForeignKey(ContentType, related_name="child_content_type", on_delete=models.CASCADE)
	child_object_id = models.PositiveIntegerField()
	child_content_object = GenericForeignKey('child_content_type', 'child_object_id')

	date = models.DateTimeField(default=timezone.now, help_text="The time at which the membership status was changed.")
	authorizer = models.ForeignKey(User, help_text="The staff member who changed the membership status of the account, project, or user in question.", on_delete=models.CASCADE)
	action = models.BooleanField(choices=Action.Choices, default=None)

	class Meta:
		ordering = ['-date']
		verbose_name_plural = 'membership histories'

	def __str__(self):
		return "Membership change for " + str(self.parent_content_type) + " " + str(self.parent_object_id)


def calculate_duration(start, end, unfinished_reason):
	"""
	Calculates the duration between two timestamps. If 'end' is None (thereby
	yielding the calculation impossible) then 'unfinished_reason' is returned.
	"""
	if start is None or end is None:
		return unfinished_reason
	else:
		return end - start


class Door(models.Model):
	name = models.CharField(max_length=100)
	area = models.ForeignKey(Area, related_name='doors', on_delete=models.PROTECT)
	interlock = models.OneToOneField(Interlock, on_delete=models.PROTECT)

	def __str__(self):
		return str(self.name)

	def get_absolute_url(self):
		return reverse('welcome_screen', args=[self.id])
	get_absolute_url.short_description = 'URL'


class PhysicalAccessLevel(models.Model):
	name = models.CharField(max_length=100)
	area = models.ForeignKey(Area, on_delete=models.CASCADE)

	class Schedule(object):
		ALWAYS = 0
		WEEKDAYS_7AM_TO_MIDNIGHT = 1
		WEEKENDS = 2
		Choices = (
			(ALWAYS, "Always"),
			(WEEKDAYS_7AM_TO_MIDNIGHT, "Weekdays, 7am to midnight"),
			(WEEKENDS, "Weekends"),
		)
	schedule = models.IntegerField(choices=Schedule.Choices)

	def accessible(self):
		now = timezone.localtime(timezone.now())
		saturday = 6
		sunday = 7
		if self.schedule == self.Schedule.ALWAYS:
			return True
		elif self.schedule == self.Schedule.WEEKDAYS_7AM_TO_MIDNIGHT:
			if now.isoweekday() == saturday or now.isoweekday() == sunday:
				return False
			seven_am = datetime.time(hour=7, tzinfo=timezone.get_current_timezone())
			midnight = datetime.time(hour=23, minute=59, second=59, tzinfo=timezone.get_current_timezone())
			current_time = now.time()
			if seven_am < current_time < midnight:
				return True
		elif self.schedule == self.Schedule.WEEKENDS:
			if now.isoweekday() == saturday or now.isoweekday() == sunday:
				return True
		return False

	def __str__(self):
		return str(self.name)

	class Meta:
		ordering = ['name']


class PhysicalAccessType(object):
	DENY = False
	ALLOW = True
	Choices = (
		(False, 'Deny'),
		(True, 'Allow'),
	)


class PhysicalAccessLog(models.Model):
	user = models.ForeignKey(User, on_delete=models.CASCADE)
	door = models.ForeignKey(Door, on_delete=models.CASCADE)
	time = models.DateTimeField()
	result = models.BooleanField(choices=PhysicalAccessType.Choices, default=None)
	details = models.TextField(null=True, blank=True, help_text="Any details that should accompany the log entry. For example, the reason physical access was denied.")

	class Meta:
		ordering = ['-time']


class SafetyIssue(models.Model):
	reporter = models.ForeignKey(User, blank=True, null=True, related_name='reported_safety_issues', on_delete=models.SET_NULL)
	location = models.CharField(max_length=200)
	creation_time = models.DateTimeField(auto_now_add=True)
	visible = models.BooleanField(default=True, help_text='Should this safety issue be visible to all users? When unchecked, the issue is only visible to staff.')
	concern = models.TextField()
	progress = models.TextField(blank=True, null=True)
	resolution = models.TextField(blank=True, null=True)
	resolved = models.BooleanField(default=False)
	resolution_time = models.DateTimeField(blank=True, null=True)
	resolver = models.ForeignKey(User, related_name='resolved_safety_issues', blank=True, null=True, on_delete=models.SET_NULL)

	class Meta:
		ordering = ['-creation_time']

	def __str__(self):
		return str(self.id)

	def get_absolute_url(self):
		from django.urls import reverse
		return reverse('update_safety_issue', args=[self.id])


class Alert(models.Model):
	title = models.CharField(blank=True, max_length=100)
	contents = models.CharField(max_length=500)
	creation_time = models.DateTimeField(default=timezone.now)
	creator = models.ForeignKey(User, null=True, blank=True, related_name='+', on_delete=models.SET_NULL)
	debut_time = models.DateTimeField(help_text='The alert will not be displayed to users until the debut time is reached.')
	expiration_time = models.DateTimeField(null=True, blank=True, help_text='The alert can be deleted after the expiration time is reached.')
	user = models.ForeignKey(User, null=True, blank=True, related_name='alerts', help_text='The alert will be visible for this user. The alert is visible to all users when this is empty.', on_delete=models.CASCADE)
	dismissible = models.BooleanField(default=False, help_text="Allows the user to delete the alert. This is only valid when the 'user' field is set.")

	class Meta:
		ordering = ['-debut_time']

	def __str__(self):
		return str(self.id)


class ContactInformationCategory(models.Model):
	name = models.CharField(max_length=200)
	display_order = models.IntegerField(help_text="Contact information categories are sorted according to display order. The lowest value category is displayed first in the 'Contact information' page.")

	class Meta:
		verbose_name_plural = 'Contact information categories'
		ordering = ['display_order', 'name']

	def __str__(self):
		return str(self.name)


class ContactInformation(models.Model):
	name = models.CharField(max_length=200)
	image = models.ImageField(blank=True, help_text='Portraits are resized to 266 pixels high and 200 pixels wide. Crop portraits to these dimensions before uploading for optimal bandwidth usage')
	category = models.ForeignKey(ContactInformationCategory, on_delete=models.CASCADE)
	email = models.EmailField(blank=True)
	office_phone = models.CharField(max_length=40, blank=True)
	office_location = models.CharField(max_length=200, blank=True)
	mobile_phone = models.CharField(max_length=40, blank=True)
	mobile_phone_is_sms_capable = models.BooleanField(default=True, verbose_name='Mobile phone is SMS capable', help_text="Is the mobile phone capable of receiving text messages? If so, a link will be displayed for users to click to send a text message to the recipient when viewing the 'Contact information' page.")

	class Meta:
		verbose_name_plural = 'Contact information'
		ordering = ['name']

	def __str__(self):
		return str(self.name)


class Notification(models.Model):
	user = models.ForeignKey(User, related_name='notifications', on_delete=models.CASCADE)
	expiration = models.DateTimeField()
	content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
	object_id = models.PositiveIntegerField()
	content_object = GenericForeignKey('content_type', 'object_id')

	class Types:
		NEWS = 'news'
		SAFETY = 'safetyissue'
		Choices = (
			(NEWS, 'News creation and updates - notifies all users'),
			(SAFETY, 'New safety issues - notifies staff only')
		)


class LandingPageChoice(models.Model):
	image = models.ImageField(help_text='An image that symbolizes the choice. It is automatically resized to 128x128 pixels when displayed, so set the image to this size before uploading to optimize bandwidth usage and landing page load time')
	name = models.CharField(max_length=40, help_text='The textual name that will be displayed underneath the image')
	url = models.CharField(max_length=200, verbose_name='URL', help_text='The URL that the choice leads to when clicked. Relative paths such as /calendar/ are used when linking within the NEMO site. Use fully qualified URL paths such as https://www.google.com/ to link to external sites.')
	display_priority = models.IntegerField(help_text="The order in which choices are displayed on the landing page, from left to right, top to bottom. Lower values are displayed first.")
	open_in_new_tab = models.BooleanField(default=False, help_text="Open the URL in a new browser tab when it's clicked")
	secure_referral = models.BooleanField(default=True, help_text="Improves security by blocking HTTP referer [sic] information from the targeted page. Enabling this prevents the target page from manipulating the calling page's DOM with JavaScript. This should always be used for external links. It is safe to uncheck this when linking within the NEMO site. Leave this box checked if you don't know what this means")
	hide_from_mobile_devices = models.BooleanField(default=False, help_text="Hides this choice when the landing page is viewed from a mobile device")
	hide_from_desktop_computers = models.BooleanField(default=False, help_text="Hides this choice when the landing page is viewed from a desktop computer")
	hide_from_users = models.BooleanField(default=False, help_text="Hides this choice from normal users. When checked, only staff, technicians, and super-users can see the choice")
	notifications = models.CharField(max_length=25, blank=True, null=True, choices=Notification.Types.Choices, help_text="Displays a the number of new notifications for the user. For example, if the user has two unread news notifications then the number '2' would appear for the news icon on the landing page.")

	class Meta:
		ordering = ['display_priority']

	def __str__(self):
		return str(self.name)


class Customization(models.Model):
	name = models.CharField(primary_key=True, max_length=50)
	value = models.TextField()

	class Meta:
		ordering = ['name']

	def __str__(self):
		return str(self.name)


class ScheduledOutageCategory(models.Model):
	name = models.CharField(max_length=200)

	class Meta:
		ordering = ['name']
		verbose_name_plural = "Scheduled outage categories"

	def __str__(self):
		return self.name


class ScheduledOutage(models.Model):
	start = models.DateTimeField()
	end = models.DateTimeField()
	creator = models.ForeignKey(User, on_delete=models.CASCADE)
	title = models.CharField(max_length=100, help_text="A brief description to quickly inform users about the outage")
	details = models.TextField(blank=True, help_text="A detailed description of why there is a scheduled outage, and what users can expect during the outage")
	category = models.CharField(blank=True, max_length=200, help_text="A categorical reason for why this outage is scheduled. Useful for trend analytics.")
	tool = models.ForeignKey(Tool, null=True, on_delete=models.CASCADE)
	resource = models.ForeignKey(Resource, null=True, on_delete=models.CASCADE)

	def __str__(self):
		return str(self.title)


class News(models.Model):
	title = models.CharField(max_length=200)
	created = models.DateTimeField(help_text="The date and time this story was first published")
	original_content = models.TextField(help_text="The content of the story when it was first published, useful for visually hiding updates 'in the middle' of the story")
	all_content = models.TextField(help_text="The entire content of the story")
	last_updated = models.DateTimeField(help_text="The date and time this story was last updated")
	last_update_content = models.TextField(help_text="The most recent update to the story, useful for visually hiding updates 'in the middle' of the story")
	archived = models.BooleanField(default=False, help_text="A story is removed from the 'Recent News' page when it is archived")
	update_count = models.PositiveIntegerField(help_text="The number of times this story has been updated. When the number of updates is greater than 2, then only the original story and the latest update are displayed in the 'Recent News' page")

	class Meta:
		ordering = ['-last_updated']
		verbose_name_plural = 'News'
