from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Union

from django.contrib.admin.widgets import FilteredSelectMultiple
from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.forms import (
    BaseForm,
    BooleanField,
    CharField,
    ChoiceField,
    DateField,
    Form,
    ImageField,
    IntegerField,
    ModelChoiceField,
    ModelForm,
    ModelMultipleChoiceField,
)
from django.forms.utils import ErrorDict, ErrorList
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from NEMO.models import (
    Account,
    AdjustmentRequest,
    Alert,
    AlertCategory,
    Area,
    BuddyRequest,
    Comment,
    Consumable,
    ConsumableWithdraw,
    Project,
    RecurringConsumableCharge,
    ReservationItemType,
    Resource,
    SafetyIssue,
    ScheduledOutage,
    StaffAbsence,
    StaffAssistanceRequest,
    Task,
    TaskCategory,
    TaskImages,
    TemporaryPhysicalAccessRequest,
    Tool,
    User,
    UserPreferences,
)
from NEMO.policy import policy_class as policy
from NEMO.utilities import (
    RecurrenceFrequency,
    bootstrap_primary_color,
    format_datetime,
    get_recurring_rule,
    localize,
    new_model_copy,
    quiet_int,
)
from NEMO.views.customization import UserRequestsCustomization


class UserForm(ModelForm):
    class Meta:
        model = User
        exclude = [
            "is_staff",
            "is_user_office",
            "is_accounting_officer",
            "is_technician",
            "is_facility_manager",
            "is_superuser",
            "groups",
            "user_permissions",
            "date_joined",
            "last_login",
            "managed_projects",
            "managed_accounts",
            "preferences",
        ]


class ProjectForm(ModelForm):
    class Meta:
        model = Project
        exclude = ["only_allow_tools", "allow_consumable_withdrawals", "allow_staff_charges"]

    managers = ModelMultipleChoiceField(
        queryset=User.objects.all(),
        required=False,
        widget=FilteredSelectMultiple(verbose_name="Principal investigators", is_stacked=False),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["managers"].initial = self.instance.manager_set.all()

    def _save_m2m(self):
        super()._save_m2m()
        exclude = self._meta.exclude
        fields = self._meta.fields
        # Check for fields and exclude
        if fields and "managers" not in fields or exclude and "managers" in exclude:
            return
        if "managers" in self.cleaned_data:
            self.instance.manager_set.set(self.cleaned_data["managers"])


class AccountForm(ModelForm):
    managers = ModelMultipleChoiceField(
        queryset=User.objects.all(),
        required=False,
        widget=FilteredSelectMultiple(verbose_name="Managers", is_stacked=False),
    )

    class Meta:
        model = Account
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["managers"].initial = self.instance.manager_set.all()

    def _save_m2m(self):
        super()._save_m2m()
        exclude = self._meta.exclude
        fields = self._meta.fields
        # Check for fields and exclude
        if fields and "managers" not in fields or exclude and "managers" in exclude:
            return
        if "managers" in self.cleaned_data:
            self.instance.manager_set.set(self.cleaned_data["managers"])


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
        cleaned_data = super().clean()
        action = cleaned_data["action"]
        if action == "create":
            if not cleaned_data["description"]:
                raise ValidationError("You must describe the problem.")
        if action == "resolve":
            if self.instance.cancelled or self.instance.resolved:
                raise ValidationError(
                    "This task can't be resolved because it is marked as 'cancelled' or 'resolved' already."
                )
        return cleaned_data

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
        fields = ["tool", "content", "staff_only", "pinned"]

    expiration = IntegerField(label="Expiration date", min_value=-1)


class SafetyIssueCreationForm(ModelForm):
    report_anonymously = BooleanField(required=False, initial=False)

    class Meta:
        model = SafetyIssue
        fields = ["reporter", "concern", "location"]

    def __init__(self, user, *args, **kwargs):
        super(SafetyIssueCreationForm, self).__init__(*args, **kwargs)
        self.user = user
        self.fields["location"].required = True

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
                + format_datetime()
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


class RecurringConsumableChargeForm(ModelForm):
    class Meta:
        model = RecurringConsumableCharge
        exclude = ("last_charge", "last_updated", "last_updated_by")

    def __init__(self, *args, **kwargs):
        locked = kwargs.pop("locked", False)
        super().__init__(*args, **kwargs)
        if locked:
            for field in self.fields:
                if field not in ["customer", "project"]:
                    self.fields[field].disabled = True

    def clean(self):
        cleaned_data = super().clean()
        if "save_and_charge" in self.data:
            # We need to require customer, which in turn if provided makes all other necessary fields be required,
            # so we can charge for this consumable.
            if not cleaned_data.get("customer"):
                self.add_error("customer", "This field is required when charging.")
        return cleaned_data


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
    copy_me = BooleanField(required=False, initial=True)

    audience = ChoiceField(
        choices=[
            ("tool", "tool"),
            ("tool-reservation", "tool-reservation"),
            ("project", "project"),
            ("project-pis", "project-pis"),
            ("account-managers", "account-managers"),
            ("account", "account"),
            ("area", "area"),
            ("user", "user"),
        ]
    )
    selection = CharField(required=False)
    no_type = BooleanField(initial=False, required=False)
    send_to_inactive_users = BooleanField(required=False, initial=False)
    send_to_expired_access_users = BooleanField(required=False, initial=False)

    def clean_title(self):
        return self.cleaned_data["title"].upper()

    def clean_selection(self):
        return self.data.getlist("selection")


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
    send_reminders = BooleanField(required=False, initial=False)
    recurring_outage = BooleanField(required=False, initial=False)
    recurrence_interval = IntegerField(required=False)
    recurrence_frequency = ChoiceField(choices=RecurrenceFrequency.choices(), required=False)
    recurrence_until = DateField(required=False)

    def clean(self):
        cleaned_data = super().clean()
        errors = {}
        recurring_outage = cleaned_data.get("recurring_outage", False)
        recurrence_until = cleaned_data.get("recurrence_until")
        recurrence_frequency = cleaned_data.get("recurrence_frequency")
        recurrence_interval = cleaned_data.get("recurrence_interval")
        if recurring_outage:
            if not recurrence_interval:
                errors["recurrence_interval"] = _("This field is required.")
            if not recurrence_frequency:
                errors["recurrence_frequency"] = _("This field is required.")
            if not recurrence_until:
                errors["recurrence_until"] = _("This field is required.")
        send_reminders = cleaned_data.get("send_reminders", False)
        reminder_days = cleaned_data.get("reminder_days")
        reminder_emails = cleaned_data.get("reminder_emails")
        if send_reminders:
            if not reminder_days:
                errors["reminder_days"] = _("This field is required.")
            if not reminder_emails:
                errors["reminder_emails"] = _("This field is required.")
        if errors:
            raise ValidationError(errors)
        return cleaned_data

    class Meta:
        model = ScheduledOutage
        exclude = ["start", "end", "resource", "creator"]


class ResourceScheduledOutageForm(ScheduledOutageForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["details"].required = True

    class Meta:
        model = ScheduledOutage
        exclude = ["tool", "area", "creator", "title"]


class UserPreferencesForm(ModelForm):
    class Meta:
        model = UserPreferences
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["tool_freed_time_notifications"].queryset = Tool.objects.filter(
            visible=True, parent_tool__isnull=True
        )
        self.fields["tool_task_notifications"].queryset = Tool.objects.filter(visible=True, parent_tool__isnull=True)

    def clean_recurring_charges_reminder_days(self):
        recurring_charges_reminder_days = self.cleaned_data["recurring_charges_reminder_days"]
        try:
            for reminder_days in recurring_charges_reminder_days.split(","):
                try:
                    int(reminder_days)
                except ValueError:
                    raise ValidationError(f"'{reminder_days}' is not a valid integer")
        except ValidationError:
            raise
        except Exception as e:
            raise ValidationError(str(e))
        return recurring_charges_reminder_days


class BuddyRequestForm(ModelForm):
    class Meta:
        model = BuddyRequest
        fields = "__all__"

    def clean(self):
        if any(self.errors):
            return
        cleaned_data = super().clean()
        start = cleaned_data.get("start")
        end = cleaned_data.get("end")
        if end < start:
            self.add_error("end", "The end must be later than the start")
        return cleaned_data


class StaffAssistanceRequestForm(ModelForm):
    class Meta:
        model = StaffAssistanceRequest
        fields = "__all__"


class TemporaryPhysicalAccessRequestForm(ModelForm):
    class Meta:
        model = TemporaryPhysicalAccessRequest
        exclude = ["creation_time", "creator", "last_updated", "last_updated_by", "status", "reviewer", "deleted"]

    def clean(self):
        if any(self.errors):
            return
        cleaned_data = super().clean()
        other_users = len(cleaned_data.get("other_users")) if "other_users" in cleaned_data else 0
        minimum_total_users = quiet_int(UserRequestsCustomization.get("access_requests_minimum_users"), 2)
        if other_users < minimum_total_users - 1:
            self.add_error(
                "other_users",
                f"You need at least {minimum_total_users - 1} other {'buddy' if minimum_total_users == 2 else 'buddies'} for this request",
            )
        return cleaned_data


class AdjustmentRequestForm(ModelForm):
    class Meta:
        model = AdjustmentRequest
        exclude = ["creation_time", "creator", "last_updated", "last_updated_by", "status", "reviewer", "deleted"]

    def clean(self) -> dict:
        cleaned_data = super().clean()
        edit = bool(self.instance.pk)
        item_type = cleaned_data.get("item_type")
        item_id = cleaned_data.get("item_id")
        if item_type and item_id and not edit:
            item = item_type.get_object_for_this_type(pk=item_id)
            new_start = cleaned_data.get("new_start")
            new_end = cleaned_data.get("new_end")
            # If the dates/quantities/projects are not changed, remove them
            # We are comparing formatted dates so we have the correct precision (otherwise user input might not have seconds/milliseconds and they would not be equal)
            if new_start and format_datetime(new_start) == format_datetime(item.start):
                cleaned_data["new_start"] = None
            if new_end and format_datetime(new_end) == format_datetime(item.end):
                cleaned_data["new_end"] = None
            # also remove quantity if not changed
            new_quantity = cleaned_data.get("new_quantity")
            if new_quantity and new_quantity == item.quantity:
                cleaned_data["new_quantity"] = None
            # also remove project if not changed
            new_project = cleaned_data.get("new_project")
            if new_project and new_project == item.project:
                cleaned_data["new_project"] = None
        return cleaned_data


class StaffAbsenceForm(ModelForm):
    class Meta:
        model = StaffAbsence
        fields = "__all__"


def save_scheduled_outage(
    form: ScheduledOutageForm,
    creator: User,
    item: Union[Resource, Tool, Area],
    start: datetime = None,
    end: datetime = None,
    title: str = None,
    check_policy=True,
):
    outage: ScheduledOutage = form.save(commit=False)
    outage.creator = creator
    outage.outage_item = item
    if title:
        outage.title = title
    if start:
        outage.start = start
    if end:
        outage.end = end
    duration = outage.end - outage.start

    if not form.cleaned_data.get("send_reminders"):
        outage.reminder_days = None
        outage.reminder_emails = None

    # If there is a policy problem for the outage then return the error...
    if check_policy:
        policy_problem = policy.check_to_create_outage(outage)
        if policy_problem:
            return policy_problem

    if form.cleaned_data.get("recurring_outage"):
        # we have to remove tz before creating rules otherwise 8am would become 7am after DST change for example.
        start_no_tz = outage.start.replace(tzinfo=None)

        submitted_frequency = form.cleaned_data.get("recurrence_frequency")
        submitted_date_until = form.cleaned_data["recurrence_until"]
        date_until_no_tz = datetime.combine(submitted_date_until, time())
        date_until_no_tz += timedelta(days=1, seconds=-1)  # set at the end of the day
        frequency = RecurrenceFrequency(quiet_int(submitted_frequency, RecurrenceFrequency.DAILY.index))
        rules = get_recurring_rule(
            start_no_tz, frequency, date_until_no_tz, int(form.cleaned_data.get("recurrence_interval", 1))
        )
        for rule in list(rules):
            new_outage = new_model_copy(outage)
            new_outage.start = localize(start_no_tz.replace(year=rule.year, month=rule.month, day=rule.day))
            new_outage.end = new_outage.start + duration
            new_outage.save()
    else:
        outage.save()


def nice_errors(obj, non_field_msg="General form errors") -> ErrorDict:
    result = ErrorDict()
    error_dict = (
        obj.errors if isinstance(obj, BaseForm) else obj.message_dict if isinstance(obj, ValidationError) else {}
    )
    for field_name, errors in error_dict.items():
        if field_name == NON_FIELD_ERRORS:
            key = non_field_msg
        elif hasattr(obj, "fields"):
            key = obj.fields[field_name].label
        else:
            key = field_name
        result[key] = ErrorList(errors)
    return result
