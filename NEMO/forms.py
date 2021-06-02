from datetime import datetime

from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.forms import (
	BaseForm,
	BooleanField,
	CharField,
	ChoiceField,
	DateField,
	Form,
	IntegerField,
	ModelChoiceField,
	ModelForm,
	ImageField,
)
from django.forms.utils import ErrorDict
from django.utils import timezone

from NEMO.models import (
	Account,
	Alert,
	Comment,
	Consumable,
	ConsumableWithdraw,
	Project,
	SafetyIssue,
	ScheduledOutage,
	Task,
	TaskCategory,
	User,
	UserPreferences,
	TaskImages,
	AlertCategory,
	ReservationItemType,
	BuddyRequest,
)
from NEMO.utilities import bootstrap_primary_color, format_datetime


class UserForm(ModelForm):
	class Meta:
		model = User
		fields = [
			"username",
			"first_name",
			"last_name",
			"email",
			"badge_number",
			"access_expiration",
			"type",
			"domain",
			"is_active",
			"training_required",
			"physical_access_levels",
			"qualifications",
			"projects",
		]


class ProjectForm(ModelForm):
	class Meta:
		model = Project
		fields = ["name", "application_identifier", "account", "active", "start_date"]


class AccountForm(ModelForm):
	class Meta:
		model = Account
		fields = ["name", "active", "type", "start_date"]


class TaskForm(ModelForm):
	problem_category = ModelChoiceField(
		queryset=TaskCategory.objects.filter(stage=TaskCategory.Stage.INITIAL_ASSESSMENT),
		required=False,
		label="Problem category",
	)
	resolution_category = ModelChoiceField(
		queryset=TaskCategory.objects.filter(stage=TaskCategory.Stage.COMPLETION),
		required=False,
		label="Resolution category",
	)
	action = ChoiceField(choices=[("create", "create"), ("update", "update"), ("resolve", "resolve")], label="Action")
	description = CharField(required=False, label="Description")

	class Meta:
		model = Task
		fields = ["tool", "urgency", "estimated_resolution_time", "force_shutdown", "safety_hazard"]

	def __init__(self, user, *args, **kwargs):
		super(TaskForm, self).__init__(*args, **kwargs)
		self.user = user
		self.fields["tool"].required = False
		self.fields["urgency"].required = False

	def clean_description(self):
		return self.cleaned_data["description"].strip()

	def clean(self):
		if any(self.errors):
			return
		super(TaskForm, self).clean()
		action = self.cleaned_data["action"]
		if action == "create":
			if not self.cleaned_data["description"]:
				raise ValidationError("You must describe the problem.")
		if action == "resolve":
			if self.instance.cancelled or self.instance.resolved:
				raise ValidationError(
					"This task can't be resolved because it is marked as 'cancelled' or 'resolved' already."
				)

	def save(self, commit=True):
		instance = super(TaskForm, self).save(commit=False)
		action = self.cleaned_data["action"]
		description = self.cleaned_data["description"]
		instance.problem_category = self.cleaned_data["problem_category"]
		now = timezone.now()
		if action == "create":
			instance.problem_description = description
			instance.urgency = (
				Task.Urgency.HIGH
				if self.cleaned_data["force_shutdown"] or self.cleaned_data["safety_hazard"]
				else Task.Urgency.NORMAL
			)
			instance.creator = self.user
		if action == "update":
			instance.last_updated = timezone.now()
			instance.last_updated_by = self.user
			instance.cancelled = False
			instance.resolved = False
			if description:
				preface = f"On {format_datetime(now)} {self.user.get_full_name()} updated this task:\n"
				if instance.progress_description is None:
					instance.progress_description = preface + description
				else:
					instance.progress_description += "\n\n" + preface + description
				instance.progress_description = instance.progress_description.strip()
		if action == "resolve":
			instance.cancelled = False
			instance.resolved = True
			instance.resolution_time = now
			instance.resolver = self.user
			if "resolution_category" in self.cleaned_data:
				instance.resolution_category = self.cleaned_data["resolution_category"]
			if "description" in self.cleaned_data:
				if instance.resolution_description:
					preface = (
						f"On {format_datetime(now)} {self.user.get_full_name()} updated the resolution information:\n"
					)
					instance.resolution_description = (
							instance.resolution_description + "\n\n" + preface + self.cleaned_data["description"]
					).strip()
				else:
					instance.resolution_description = self.cleaned_data["description"]
		return super(TaskForm, self).save(commit=True)


class TaskImagesForm(ModelForm):
	image = ImageField(label="Images", required=False)

	class Meta:
		model = TaskImages
		fields = ("image",)


class CommentForm(ModelForm):
	class Meta:
		model = Comment
		fields = ["tool", "content", "staff_only"]

	expiration = IntegerField(label="Expiration date", min_value=0)


class SafetyIssueCreationForm(ModelForm):
	report_anonymously = BooleanField(required=False, initial=False)

	class Meta:
		model = SafetyIssue
		fields = ["reporter", "concern", "location"]

	def __init__(self, user, *args, **kwargs):
		super(SafetyIssueCreationForm, self).__init__(*args, **kwargs)
		self.user = user

	def clean_update(self):
		return self.cleaned_data["concern"].strip()

	def clean_location(self):
		return self.cleaned_data["location"].strip()

	def save(self, commit=True):
		instance = super(SafetyIssueCreationForm, self).save(commit=False)
		if not self.cleaned_data["report_anonymously"]:
			self.instance.reporter = self.user
		if commit:
			instance.save()
		return super(SafetyIssueCreationForm, self).save(commit=commit)


class SafetyIssueUpdateForm(ModelForm):
	update = CharField(required=False, label="Update")

	class Meta:
		model = SafetyIssue
		fields = ["resolved", "visible"]

	def __init__(self, user, *args, **kwargs):
		super(SafetyIssueUpdateForm, self).__init__(*args, **kwargs)
		self.user = user

	def clean_update(self):
		return self.cleaned_data["update"].strip()

	def save(self, commit=True):
		instance = super(SafetyIssueUpdateForm, self).save(commit=False)
		progress_type = "resolved" if self.cleaned_data["resolved"] else "updated"
		if progress_type == "resolved":
			instance.resolution = self.cleaned_data["update"]
			instance.resolution_time = timezone.now()
			instance.resolver = self.user
		if progress_type == "updated" and self.cleaned_data["update"]:
			progress = (
					"On "
					+ format_datetime(timezone.now())
					+ " "
					+ self.user.get_full_name()
					+ " updated this issue:\n"
					+ self.cleaned_data["update"]
			)
			if instance.progress:
				instance.progress += "\n\n" + progress
			else:
				instance.progress = progress
		return super(SafetyIssueUpdateForm, self).save(commit=commit)


class ConsumableWithdrawForm(ModelForm):
	class Meta:
		model = ConsumableWithdraw
		fields = ["customer", "project", "consumable", "quantity"]

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.fields["consumable"].queryset = Consumable.objects.filter(visible=True)

	def clean_customer(self):
		customer = self.cleaned_data["customer"]
		if not customer.is_active:
			raise ValidationError(
				"A consumable withdraw was requested for an inactive user. Only active users may withdraw consumables."
			)
		return customer

	def clean_project(self):
		project = self.cleaned_data["project"]
		if not project.active:
			raise ValidationError(
				"A consumable may only be billed to an active project. The user's project is inactive."
			)
		if not project.account.active:
			raise ValidationError(
				"A consumable may only be billed to a project that belongs to an active account. The user's account is inactive."
			)
		return project

	def clean_quantity(self):
		quantity = self.cleaned_data["quantity"]
		if quantity < 1:
			raise ValidationError("Please specify a valid quantity of items to withdraw.")
		return quantity

	def clean(self):
		if any(self.errors):
			return
		super(ConsumableWithdrawForm, self).clean()
		quantity = self.cleaned_data["quantity"]
		consumable = self.cleaned_data["consumable"]
		if quantity > consumable.quantity:
			raise ValidationError(
				'There are not enough "' + consumable.name + '". (The current quantity in stock is '
				+ str(consumable.quantity)
				+ "). Please order more as soon as possible."
			)
		customer = self.cleaned_data["customer"]
		project = self.cleaned_data["project"]
		if project not in customer.active_projects():
			raise ValidationError(
				"{} is not a member of the project {}. Users can only bill to projects they belong to.".format(
					customer, project
				)
			)


class ReservationAbuseForm(Form):
	cancellation_horizon = IntegerField(initial=6, min_value=1)
	cancellation_penalty = IntegerField(initial=10)
	target = CharField(required=False)
	start = DateField(initial=timezone.now().replace(day=1).date())
	end = DateField(initial=timezone.now().date())

	def clean_cancellation_horizon(self):
		# Convert the cancellation horizon from hours to seconds.
		return self.cleaned_data["cancellation_horizon"] * 60 * 60

	def clean_start(self):
		start = self.cleaned_data["start"]
		return timezone.make_aware(
			datetime(year=start.year, month=start.month, day=start.day, hour=0, minute=0, second=0, microsecond=0),
			timezone.get_current_timezone(),
		)

	def clean_end(self):
		end = self.cleaned_data["end"]
		return timezone.make_aware(
			datetime(year=end.year, month=end.month, day=end.day, hour=23, minute=59, second=59, microsecond=999999),
			timezone.get_current_timezone(),
		)

	def get_target(self):
		target = self.cleaned_data["target"].split("|", 1)
		return ReservationItemType(target[0]), int(target[1])


class EmailBroadcastForm(Form):
	subject = CharField(required=False)
	color = ChoiceField(
		choices=(
			(bootstrap_primary_color("info"), "info"),
			(bootstrap_primary_color("success"), "success"),
			(bootstrap_primary_color("warning"), "warning"),
			(bootstrap_primary_color("danger"), "danger"),
		)
	)
	title = CharField(required=False)
	greeting = CharField(required=False)
	contents = CharField(required=False)
	copy_me = BooleanField(initial=True)

	audience = ChoiceField(choices=[("tool", "tool"), ("project", "project"), ("account", "account")])
	selection = IntegerField()
	only_active_users = BooleanField(initial=True)

	def clean_title(self):
		return self.cleaned_data["title"].upper()


class AlertForm(ModelForm):
	class Meta:
		model = Alert
		fields = ["title", "category", "contents", "debut_time", "expiration_time"]

	def clean_category(self):
		category = self.cleaned_data["category"]
		if not category and AlertCategory.objects.exists():
			raise ValidationError("Please select a category.")
		return category


class ScheduledOutageForm(ModelForm):
	def __init__(self, *positional_arguments, **keyword_arguments):
		super().__init__(*positional_arguments, **keyword_arguments)
		self.fields["details"].required = True

	class Meta:
		model = ScheduledOutage
		fields = ["details", "start", "end", "resource", "category"]


class UserPreferencesForm(ModelForm):
	class Meta:
		model = UserPreferences
		fields = [
			"attach_created_reservation",
			"attach_cancelled_reservation",
			"display_new_buddy_request_notification",
			"display_new_buddy_request_reply_notification",
			"email_new_buddy_request_reply",
		]


class BuddyRequestForm(ModelForm):
	class Meta:
		model = BuddyRequest
		fields = "__all__"


def nice_errors(form, non_field_msg="General form errors"):
	result = ErrorDict()
	if isinstance(form, BaseForm):
		for field, errors in form.errors.items():
			if field == NON_FIELD_ERRORS:
				key = non_field_msg
			else:
				key = form.fields[field].label
			result[key] = errors
	return result
