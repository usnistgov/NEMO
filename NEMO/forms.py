from datetime import datetime

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

from NEMO.models import (
    Account,
    AdjustmentRequest,
    Alert,
    AlertCategory,
    BuddyRequest,
    Comment,
    Consumable,
    ConsumableWithdraw,
    Project,
    RecurringConsumableCharge,
    ReservationItemType,
    SafetyIssue,
    ScheduledOutage,
    StaffAbsence,
    Task,
    TaskCategory,
    TaskImages,
    TemporaryPhysicalAccessRequest,
    Tool,
    User,
    UserPreferences,
)
from NEMO.utilities import bootstrap_primary_color, format_datetime, quiet_int
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
            "preferences",
        ]


class ProjectForm(ModelForm):
    class Meta:
        model = Project
        exclude = ["only_allow_tools", "allow_consumable_withdrawals"]

    principal_investigators = ModelMultipleChoiceField(
        queryset=User.objects.all(),
        required=False,
        widget=FilteredSelectMultiple(verbose_name="Principal investigators", is_stacked=False),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["principal_investigators"].initial = self.instance.manager_set.all()

    def _save_m2m(self):
        super()._save_m2m()
        exclude = self._meta.exclude
        fields = self._meta.fields
        # Check for fields and exclude
        if fields and "principal_investigators" not in fields or exclude and "principal_investigators" in exclude:
            return
        if "principal_investigators" in self.cleaned_data:
            self.instance.manager_set.set(self.cleaned_data["principal_investigators"])


class AccountForm(ModelForm):
    class Meta:
        model = Account
        fields = "__all__"


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
        fields = ["tool", "content", "staff_only"]

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
            ("account", "account"),
            ("area", "area"),
            ("user", "user"),
        ]
    )
    selection = CharField(required=False)
    no_type = BooleanField(initial=False, required=False)
    only_active_users = BooleanField(required=False, initial=True)

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
    def __init__(self, *positional_arguments, **keyword_arguments):
        super().__init__(*positional_arguments, **keyword_arguments)
        self.fields["details"].required = True

    class Meta:
        model = ScheduledOutage
        fields = ["details", "start", "end", "resource", "category"]


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


class StaffAbsenceForm(ModelForm):
    class Meta:
        model = StaffAbsence
        fields = "__all__"


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
