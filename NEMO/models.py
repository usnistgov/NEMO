import datetime
import socket
import struct
from datetime import timedelta

from django.conf import settings
from django.contrib import auth
from django.contrib.auth.models import BaseUserManager, Group, Permission
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.mail import send_mail
from django.db import models
from django.db.models import Q
from django.db.models.signals import pre_delete
from django.urls import reverse
from django.utils import timezone

from NEMO.utilities import format_datetime
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

	def email_user(self, subject, message, from_email=None):
		""" Sends an email to this user. """
		send_mail(subject=subject, message='', from_email=from_email, recipient_list=[self.email], html_message=message)

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
	category = models.CharField(max_length=1000, help_text="Create sub-categories using slashes. For example \"Category 1/Sub-category 1\".")
	visible = models.BooleanField(default=True, help_text="Specifies whether this tool is visible to users.")
	operational = models.BooleanField(default=False, help_text="Marking the tool non-operational will prevent users from using the tool.")
	primary_owner = models.ForeignKey(User, related_name="primary_tool_owner", help_text="The staff member who is responsible for administration of this tool.")
	backup_owners = models.ManyToManyField(User, blank=True, related_name="backup_for_tools", help_text="Alternate staff members who are responsible for administration of this tool when the primary owner is unavailable.")
	location = models.CharField(max_length=100)
	phone_number = models.CharField(max_length=100)
	notification_email_address = models.EmailField(blank=True, null=True, help_text="Messages that relate to this tool (such as comments, problems, and shutdowns) will be forwarded to this email address. This can be a normal email address or a mailing list address.")
	# Policy fields:
	requires_area_access = models.ForeignKey('Area', null=True, blank=True, help_text="Indicates that this tool is physically located in a billable area and requires an active area access record in order to be operated.")
	interlock = models.OneToOneField('Interlock', blank=True, null=True, on_delete=models.SET_NULL)
	reservation_horizon = models.PositiveIntegerField(default=14, null=True, blank=True, help_text="Users may create reservations this many days in advance. Leave this field blank to indicate that no reservation horizon exists for this tool.")
	minimum_usage_block_time = models.PositiveIntegerField(null=True, blank=True, help_text="The minimum amount of time (in minutes) that a user must reserve this tool for a single reservation. Leave this field blank to indicate that no minimum usage block time exists for this tool.")
	maximum_usage_block_time = models.PositiveIntegerField(null=True, blank=True, help_text="The maximum amount of time (in minutes) that a user may reserve this tool for a single reservation. Leave this field blank to indicate that no maximum usage block time exists for this tool.")
	maximum_reservations_per_day = models.PositiveIntegerField(null=True, blank=True, help_text="The maximum number of reservations a user may make per day for this tool.")
	minimum_time_between_reservations = models.PositiveIntegerField(null=True, blank=True, help_text="The minimum amount of time (in minutes) that the same user must have between any two reservations for this tool.")
	maximum_future_reservation_time = models.PositiveIntegerField(null=True, blank=True, help_text="The maximum amount of time (in minutes) that a user may reserve from the current time onwards.")
	missed_reservation_threshold = models.PositiveIntegerField(null=True, blank=True, help_text="The amount of time (in minutes) that a tool reservation may go unused before it is automatically marked as \"missed\" and hidden from the calendar. Usage can be from any user, regardless of who the reservation was originally created for. The cancellation process is triggered by a timed job on the web server.")
	allow_delayed_logoff = models.BooleanField(default=False, help_text='Upon logging off users may enter a delay before another user may use the tool. Some tools require "spin-down" or cleaning time after use.')
	post_usage_questions = models.TextField(null=True, blank=True, help_text="")

	class Meta:
		ordering = ['name']

	def __str__(self):
		return self.name

	def get_absolute_url(self):
		from django.urls import reverse
		return reverse('tool_control', args=[self.id])

	def problematic(self):
		return self.task_set.filter(resolved=False, cancelled=False).exists()
	problematic.admin_order_field = 'task'
	problematic.boolean = True

	def problems(self):
		return self.task_set.filter(resolved=False, cancelled=False)

	def comments(self):
		unexpired = Q(expiration_date__isnull=True) | Q(expiration_date__gt=timezone.now())
		return self.comment_set.filter(visible=True).filter(unexpired)

	def required_resource_is_unavailable(self):
		return self.required_resource_set.filter(available=False).exists()

	def nonrequired_resource_is_unavailable(self):
		return self.nonrequired_resource_set.filter(available=False).exists()

	def all_resources_available(self):
		required_resources_available = not self.unavailable_required_resources().exists()
		nonrequired_resources_available = not self.unavailable_nonrequired_resources().exists()
		if required_resources_available and nonrequired_resources_available:
			return True
		return False

	def unavailable_required_resources(self):
		return self.required_resource_set.filter(available=False)

	def unavailable_nonrequired_resources(self):
		return self.nonrequired_resource_set.filter(available=False)

	def in_use(self):
		result = UsageEvent.objects.filter(tool=self.id, end=None).exists()
		return result

	def delayed_logoff_in_progress(self):
		result = UsageEvent.objects.filter(tool=self.id, end__gt=timezone.now()).exists()
		return result

	def get_delayed_logoff_usage_event(self):
		try:
			return UsageEvent.objects.get(tool=self.id, end__gt=timezone.now())
		except UsageEvent.DoesNotExist:
			return None

	def scheduled_outages(self):
		""" Returns a QuerySet of scheduled outages that are in progress for this tool. This includes tool outages, and resources outages (when the tool fully depends on the resource). """
		return ScheduledOutage.objects.filter(Q(tool=self.id) | Q(resource__fully_dependent_tools__in=[self.id]), start__lte=timezone.now(), end__gt=timezone.now())

	def scheduled_outage_in_progress(self):
		""" Returns a true if a tool or resource outage is currently in effect for this tool. Otherwise, returns false. """
		return ScheduledOutage.objects.filter(Q(tool=self.id) | Q(resource__fully_dependent_tools__in=[self.id]), start__lte=timezone.now(), end__gt=timezone.now()).exists()

	def is_configurable(self):
		return self.configuration_set.exists()
	is_configurable.admin_order_field = 'configuration'
	is_configurable.boolean = True
	is_configurable.short_description = 'Configurable'

	def get_configuration_information(self, user, start):
		configurations = self.configuration_set.all().order_by('display_priority')
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
			'configurations': self.configuration_set.all().order_by('display_priority'),
			'user': user
		}
		configurations = ConfigurationEditor()
		return configurations.render(None, config_input)

	def get_current_usage_event(self):
		""" Gets the usage event for the current user of this tool. """
		try:
			return UsageEvent.objects.get(end=None, tool=self.id)
		except UsageEvent.DoesNotExist:
			return None


class Configuration(models.Model):
	tool = models.ForeignKey(Tool, help_text="The tool that this configuration option applies to.")
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
		if user in self.maintainers.all():
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

	trainer = models.ForeignKey(User, related_name="teacher_set")
	trainee = models.ForeignKey(User, related_name="student_set")
	tool = models.ForeignKey(Tool)
	project = models.ForeignKey('Project')
	duration = models.PositiveIntegerField(help_text="The duration of the training session in minutes.")
	type = models.IntegerField(choices=Type.Choices)
	date = models.DateTimeField(default=timezone.now)
	qualified = models.BooleanField(default=False, help_text="Indicates that after this training session the user was qualified to use the tool.")

	class Meta:
		ordering = ['-date']

	def __str__(self):
		return str(self.id)


class StaffCharge(CalendarDisplay):
	staff_member = models.ForeignKey(User, related_name='staff_charge_actor')
	customer = models.ForeignKey(User, related_name='staff_charge_customer')
	project = models.ForeignKey('Project')
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
	area = models.ForeignKey(Area)
	customer = models.ForeignKey(User)
	project = models.ForeignKey('Project')
	start = models.DateTimeField(default=timezone.now)
	end = models.DateTimeField(null=True, blank=True)
	staff_charge = models.ForeignKey(StaffCharge, blank=True, null=True)

	class Meta:
		ordering = ['-start']

	def __str__(self):
		return str(self.id)


class ConfigurationHistory(models.Model):
	configuration = models.ForeignKey(Configuration)
	user = models.ForeignKey(User)
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
	account = models.ForeignKey(Account, help_text="All charges for this project will be billed to the selected account.")
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
	user = models.ForeignKey(User, related_name="reservation_user")
	creator = models.ForeignKey(User, related_name="reservation_creator")
	creation_time = models.DateTimeField(default=timezone.now)
	tool = models.ForeignKey(Tool)
	project = models.ForeignKey(Project, null=True, blank=True, help_text="Indicates the intended project for this reservation. A missed reservation would be billed to this project.")
	start = models.DateTimeField('start')
	end = models.DateTimeField('end')
	short_notice = models.BooleanField(default=None, help_text="Indicates that the reservation was made after the configuration deadline for a tool. NanoFab staff may not have enough time to properly configure the tool before the user is scheduled to use it.")
	cancelled = models.BooleanField(default=False, help_text="Indicates that the reservation has been cancelled, moved, or resized.")
	cancellation_time = models.DateTimeField(null=True, blank=True)
	cancelled_by = models.ForeignKey(User, null=True, blank=True)
	missed = models.BooleanField(default=False, help_text="Indicates that the tool was not enabled by anyone before the tool's \"missed reservation threshold\" passed.")
	shortened = models.BooleanField(default=False, help_text="Indicates that the user finished using the tool and relinquished the remaining time on their reservation. The reservation will no longer be visible on the calendar and a descendant reservation will be created in place of the existing one.")
	descendant = models.OneToOneField('Reservation', related_name='ancestor', null=True, blank=True, help_text="Any time a reservation is moved or resized, the old reservation is cancelled and a new reservation with updated information takes its place. This field links the old reservation to the new one, so the history of reservation moves & changes can be easily tracked.")
	additional_information = models.TextField(null=True, blank=True)
	self_configuration = models.BooleanField(default=False, help_text="When checked, indicates that the user will perform their own tool configuration (instead of requesting that the NanoFab staff configure it for them).")
	title = models.TextField(default='', blank=True, max_length=200, help_text="Shows a custom title for this reservation on the calendar. Leave this field blank to display the reservation's user name as the title (which is the default behaviour).")

	def duration(self):
		return self.end - self.start

	def has_not_ended(self):
		return False if self.end < timezone.now() else True

	class Meta:
		ordering = ['-start']

	def __str__(self):
		return str(self.id)


class UsageEvent(CalendarDisplay):
	user = models.ForeignKey(User, related_name="usage_event_user")
	operator = models.ForeignKey(User, related_name="usage_event_operator")
	project = models.ForeignKey(Project)
	tool = models.ForeignKey(Tool, related_name='+')  # The related_name='+' disallows reverse lookups. Helper functions of other models should be used instead.
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
	category = models.ForeignKey('ConsumableCategory', blank=True, null=True)
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
	customer = models.ForeignKey(User, related_name="consumable_user", help_text="The user who will use the consumable item.")
	merchant = models.ForeignKey(User, related_name="consumable_merchant", help_text="The staff member that performed the withdraw.")
	consumable = models.ForeignKey(Consumable)
	quantity = models.PositiveIntegerField()
	project = models.ForeignKey(Project, help_text="The withdraw will be billed to this project.")
	date = models.DateTimeField(default=timezone.now, help_text="The date and time when the user withdrew the consumable.")

	class Meta:
		ordering = ['-date']

	def __str__(self):
		return str(self.id)


class InterlockCard(models.Model):
	server = models.CharField(max_length=100)
	port = models.PositiveIntegerField()
	number = models.PositiveIntegerField()
	even_port = models.PositiveIntegerField()
	odd_port = models.PositiveIntegerField()

	class Meta:
		ordering = ['server', 'number']

	def __str__(self):
		return str(self.server) + ', card ' + str(self.number)


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

	card = models.ForeignKey(InterlockCard)
	channel = models.PositiveIntegerField()
	state = models.IntegerField(choices=State.Choices, default=State.UNKNOWN)
	most_recent_reply = models.TextField(default="None")

	def unlock(self):
		return self.__issue_command(self.State.UNLOCKED)

	def lock(self):
		return self.__issue_command(self.State.LOCKED)

	def __issue_command(self, command_type):
		if settings.DEBUG:
			self.most_recent_reply = "Interlock interface mocked out because settings.DEBUG = True. Interlock last set on " + format_datetime(timezone.now()) + "."
			self.state = command_type
			self.save()
			return True

		# The string in this next function call identifies the format of the interlock message.
		# '!' means use network byte order (big endian) for the contents of the message.
		# '20s' means that the message begins with a 20 character string.
		# Each 'i' is an integer field (4 bytes).
		# Each 'b' is a byte field (1 byte).
		# '18s' means that the message ends with a 18 character string.
		# More information on Python structs can be found at:
		# http://docs.python.org/library/struct.html
		command_schema = struct.Struct('!20siiiiiiiiibbbbb18s')
		command_message = command_schema.pack(
			b'EQCNTL_BEGIN_COMMAND',
			1,  # Instruction count
			self.card.number,
			self.card.even_port,
			self.card.odd_port,
			self.channel,
			0,  # Command return value
			command_type,  # Type
			0,  # Command
			0,  # Delay
			0,  # SD overload
			0,  # RD overload
			0,  # ADC done
			0,  # Busy
			0,  # Instruction return value
			b'EQCNTL_END_COMMAND'
		)

		reply_message = ""

		# Create a TCP socket to send the interlock command.
		sock = socket.socket()
		try:
			sock.settimeout(3.0)  # Set the send/receive timeout to be 3 seconds.
			server_address = (self.card.server, self.card.port)
			sock.connect(server_address)
			sock.send(command_message)
			# The reply schema is the same as the command schema except there are no start and end strings.
			reply_schema = struct.Struct('!iiiiiiiiibbbbb')
			reply = sock.recv(reply_schema.size)
			reply = reply_schema.unpack(reply)

			# Update the state of the interlock in the database if the command succeeded.
			if reply[5]:
				self.state = command_type
			else:
				self.state = self.State.UNKNOWN

			# Compose the status message of the last command and write it to the database.
			reply_message = "Reply received at " + format_datetime(timezone.now()) + ". "
			if command_type == self.State.UNLOCKED:
				reply_message += "Unlock"
			elif command_type == self.State.LOCKED:
				reply_message += "Lock"
			else:
				reply_message += "Unknown"
			reply_message += " command "
			if reply[5]:  # Index 5 of the reply is the return value of the whole command.
				reply_message += "succeeded."
			else:
				reply_message += "failed. Response information: " +\
								"Instruction count = " + str(reply[0]) + ", " +\
								"card number = " + str(reply[1]) + ", " +\
								"even port = " + str(reply[2]) + ", " +\
								"odd port = " + str(reply[3]) + ", " +\
								"channel = " + str(reply[4]) + ", " +\
								"command return value = " + str(reply[5]) + ", " +\
								"instruction type = " + str(reply[6]) + ", " +\
								"instruction = " + str(reply[7]) + ", " +\
								"delay = " + str(reply[8]) + ", " +\
								"SD overload = " + str(reply[9]) + ", " +\
								"RD overload = " + str(reply[10]) + ", " +\
								"ADC done = " + str(reply[11]) + ", " +\
								"busy = " + str(reply[12]) + ", " +\
								"instruction return value = " + str(reply[13]) + "."

		# Log any errors that occurred during the operation into the database.
		except OSError as error:
			reply_message = "Socket error"
			if error.errno:
				reply_message += " " + str(error.errno)
			reply_message += ": " + str(error)
			self.state = self.State.UNKNOWN
		except struct.error as error:
			reply_message = "Response format error. " + str(error)
			self.state = self.State.UNKNOWN
		except Exception as error:
			reply_message = "General exception. " + str(error)
			self.state = self.State.UNKNOWN
		finally:
			sock.close()
			self.most_recent_reply = reply_message
			self.save()
			# If the command type equals the current state then the command worked which will return true:
			return self.state == command_type

	class Meta:
		unique_together = ('card', 'channel')
		ordering = ['card__server', 'card__number', 'channel']

	def __str__(self):
		return str(self.card) + ", channel " + str(self.channel)


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
	tool = models.ForeignKey(Tool, help_text="The tool that this task relates to.")
	force_shutdown = models.BooleanField(default=None, help_text="Indicates that the tool this task relates to will be shutdown until the task is resolved.")
	safety_hazard = models.BooleanField(default=None, help_text="Indicates that this task represents a safety hazard to the NanoFab.")
	creator = models.ForeignKey(User, related_name="created_tasks", help_text="The user who created the task.")
	creation_time = models.DateTimeField(default=timezone.now, help_text="The date and time when the task was created.")
	problem_category = models.ForeignKey('TaskCategory', null=True, blank=True, related_name='problem_category')
	problem_description = models.TextField(blank=True, null=True)
	progress_description = models.TextField(blank=True, null=True)
	last_updated = models.DateTimeField(null=True, blank=True, help_text="The last time this task was modified. (Creating the task does not count as modifying it.)")
	last_updated_by = models.ForeignKey(User, null=True, blank=True, help_text="The last user who modified this task. This should always be a staff member.")
	estimated_resolution_time = models.DateTimeField(null=True, blank=True, help_text="The estimated date and time that the task will be resolved.")
	cancelled = models.BooleanField(default=False)
	resolved = models.BooleanField(default=False)
	resolution_time = models.DateTimeField(null=True, blank=True, help_text="The timestamp of when the task was marked complete or cancelled.")
	resolver = models.ForeignKey(User, null=True, blank=True, related_name='task_resolver', help_text="The staff member who resolved the task.")
	resolution_description = models.TextField(blank=True, null=True)
	resolution_category = models.ForeignKey('TaskCategory', null=True, blank=True, related_name='resolution_category')

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
	task = models.ForeignKey(Task, help_text='The task that this historical entry refers to', related_name='history')
	status = models.CharField(max_length=200, help_text="A text description of the task's status")
	time = models.DateTimeField(auto_now_add=True, help_text='The date and time when the task status was changed')
	user = models.ForeignKey(User, help_text='The user that changed the task to this status')

	class Meta:
		verbose_name_plural = 'task histories'
		ordering = ['time']
		get_latest_by = 'time'


class Comment(models.Model):
	tool = models.ForeignKey(Tool, help_text="The tool that this comment relates to.")
	author = models.ForeignKey(User)
	creation_date = models.DateTimeField(default=timezone.now)
	expiration_date = models.DateTimeField(blank=True, null=True, help_text="The comment will only be visible until this date.")
	visible = models.BooleanField(default=True)
	hide_date = models.DateTimeField(blank=True, null=True, help_text="The date when this comment was hidden. If it is still visible or has expired then this date should be empty.")
	hidden_by = models.ForeignKey(User, null=True, blank=True, related_name="hidden_comments")
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
	category = models.ForeignKey(ResourceCategory, blank=True, null=True)
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

	content_type = models.ForeignKey(ContentType)
	object_id = models.PositiveIntegerField()
	content_object = GenericForeignKey('content_type', 'object_id')
	action = models.BooleanField(choices=Action.Choices, default=None, help_text="The target state (activated or deactivated).")
	date = models.DateTimeField(default=timezone.now, help_text="The time at which the active state was changed.")
	authorizer = models.ForeignKey(User, help_text="The staff member who changed the active state of the account, project, or user in question.")

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
	parent_content_type = models.ForeignKey(ContentType, related_name="parent_content_type")
	parent_object_id = models.PositiveIntegerField()
	parent_content_object = GenericForeignKey('parent_content_type', 'parent_object_id')

	# The child entity can be either a project or user.
	child_content_type = models.ForeignKey(ContentType, related_name="child_content_type")
	child_object_id = models.PositiveIntegerField()
	child_content_object = GenericForeignKey('child_content_type', 'child_object_id')

	date = models.DateTimeField(default=timezone.now, help_text="The time at which the membership status was changed.")
	authorizer = models.ForeignKey(User, help_text="The staff member who changed the membership status of the account, project, or user in question.")
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
	area = models.ForeignKey(Area, related_name='doors')
	interlock = models.OneToOneField(Interlock)

	def __str__(self):
		return str(self.name)

	def get_absolute_url(self):
		return reverse('welcome_screen', args=[self.id])
	get_absolute_url.short_description = 'URL'


class PhysicalAccessLevel(models.Model):
	name = models.CharField(max_length=100)
	area = models.ForeignKey(Area)

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
	user = models.ForeignKey(User)
	door = models.ForeignKey(Door)
	time = models.DateTimeField()
	result = models.BooleanField(choices=PhysicalAccessType.Choices, default=None)
	details = models.TextField(null=True, blank=True, help_text="Any details that should accompany the log entry. For example, the reason physical access was denied.")

	class Meta:
		ordering = ['-time']


class SafetyIssue(models.Model):
	reporter = models.ForeignKey(User, blank=True, null=True, related_name='reported_safety_issues')
	location = models.CharField(max_length=200)
	creation_time = models.DateTimeField(auto_now_add=True)
	visible = models.BooleanField(default=True, help_text='Should this safety issue be visible to all users? When unchecked, the issue is only visible to staff.')
	concern = models.TextField()
	progress = models.TextField(blank=True, null=True)
	resolution = models.TextField(blank=True, null=True)
	resolved = models.BooleanField(default=False)
	resolution_time = models.DateTimeField(blank=True, null=True)
	resolver = models.ForeignKey(User, related_name='resolved_safety_issues', blank=True, null=True)

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
	creator = models.ForeignKey(User, null=True, blank=True, related_name='+')
	debut_time = models.DateTimeField(help_text='The alert will not be displayed to users until the debut time is reached.')
	expiration_time = models.DateTimeField(null=True, blank=True, help_text='The alert can be deleted after the expiration time is reached.')
	user = models.ForeignKey(User, null=True, blank=True, related_name='alerts', help_text='The alert will be visible for this user. The alert is visible to all users when this is empty.')
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
	category = models.ForeignKey(ContactInformationCategory)
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
	user = models.ForeignKey(User, related_name='notifications')
	expiration = models.DateTimeField()
	content_type = models.ForeignKey(ContentType)
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
	creator = models.ForeignKey(User)
	title = models.CharField(max_length=100, help_text="A brief description to quickly inform users about the outage")
	details = models.TextField(blank=True, help_text="A detailed description of why there is a scheduled outage, and what users can expect during the outage")
	category = models.CharField(blank=True, max_length=200, help_text="A categorical reason for why this outage is scheduled. Useful for trend analytics.")
	tool = models.ForeignKey(Tool, null=True)
	resource = models.ForeignKey(Resource, null=True)

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
