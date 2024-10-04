from __future__ import annotations

import datetime
import os
import sys
from datetime import timedelta
from enum import Enum
from html import escape
from json import loads
from logging import getLogger
from re import match
from typing import Dict, List, Optional, Set, Union

from django.conf import settings
from django.contrib.auth.models import BaseUserManager, Group, Permission, PermissionsMixin
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.core.validators import MinValueValidator, validate_comma_separated_integer_list
from django.db import connections, models, transaction
from django.db.models import Q
from django.db.models.manager import Manager
from django.db.models.signals import pre_delete
from django.dispatch import receiver
from django.template import loader
from django.template.defaultfilters import linebreaksbr
from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _
from mptt.fields import TreeForeignKey, TreeManyToManyField
from mptt.models import MPTTModel

from NEMO import fields
from NEMO.mixins import BillableItemMixin, CalendarDisplayMixin, ConfigurationMixin, RecurrenceMixin
from NEMO.typing import QuerySetType
from NEMO.utilities import (
    EmailCategory,
    RecurrenceFrequency,
    as_timezone,
    bootstrap_primary_color,
    distinct_qs_value_list,
    document_filename_upload,
    format_daterange,
    format_datetime,
    get_chemical_document_filename,
    get_duration_with_off_schedule,
    get_full_url,
    get_hazard_logo_filename,
    get_model_instance,
    get_task_image_filename,
    get_tool_image_filename,
    new_model_copy,
    render_email_template,
    send_mail,
    supported_embedded_extensions,
)
from NEMO.validators import color_hex_list_validator, color_hex_validator
from NEMO.views.constants import (
    ADDITIONAL_INFORMATION_MAXIMUM_LENGTH,
    CHAR_FIELD_LARGE_LENGTH,
    CHAR_FIELD_MEDIUM_LENGTH,
    CHAR_FIELD_SMALL_LENGTH,
    MEDIA_PROTECTED,
)
from NEMO.widgets.configuration_editor import ConfigurationEditor

models_logger = getLogger(__name__)


class BaseQuerySet(models.query.QuerySet):
    def distinct(self, *field_names):
        # If using Oracle, distinct and CLOBs don't work together, so we have to use defer to ignore them
        # However, defer can only be used when no specific fields are present
        # The error is "ORA-00932: inconsistent datatypes: expected - got NCLOB"
        # See https://code.djangoproject.com/ticket/4186
        if self.is_oracle_vendor() and self._fields is None:
            return super().distinct(*field_names).defer(*self.model_text_fields())
        else:
            return super().distinct(*field_names)

    def is_oracle_vendor(self) -> bool:
        connection = connections[self.db]
        return getattr(connection, "vendor", "") == "oracle"

    def model_text_fields(self) -> List[str]:
        return [f.name for f in self.model._meta.fields if isinstance(f, models.TextField)]


class BaseManager(Manager.from_queryset(BaseQuerySet)):
    pass


class DeserializationByNameManager(BaseManager):
    """Deserialization manager using name field"""

    def get_by_natural_key(self, name):
        return self.get(name=name)


class UserManager(BaseUserManager.from_queryset(BaseQuerySet)):
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


class BaseModel(models.Model):
    objects = BaseManager()

    class Meta:
        abstract = True


class SerializationByNameModel(BaseModel):
    """Serialization model using name field"""

    objects = DeserializationByNameManager()

    class Meta:
        abstract = True

    def natural_key(self):
        return (self.name,)


class BaseCategory(SerializationByNameModel):
    name = models.CharField(max_length=CHAR_FIELD_MEDIUM_LENGTH, unique=True, help_text="The unique name for this item")
    display_order = models.IntegerField(
        help_text="The display order is used to sort these items. The lowest value category is displayed first."
    )

    class Meta:
        abstract = True
        ordering = ["display_order", "name"]

    def __str__(self):
        return str(self.name)


class BaseDocumentModel(BaseModel):
    document = models.FileField(
        max_length=CHAR_FIELD_MEDIUM_LENGTH,
        null=True,
        blank=True,
        upload_to=document_filename_upload,
        verbose_name="Document",
    )
    url = models.URLField(null=True, blank=True, verbose_name="URL")
    name = models.CharField(
        null=True,
        blank=True,
        max_length=CHAR_FIELD_MEDIUM_LENGTH,
        help_text="The optional name to display for this document",
    )
    display_order = models.IntegerField(
        default=1,
        help_text="The order in which choices are displayed on the landing page, from left to right, top to bottom. Lower values are displayed first.",
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def get_filename_upload(self, filename):
        raise NotImplementedError("subclasses must provide a filename for upload")

    def filename(self):
        return (
            self.name
            if self.name
            else (
                os.path.basename(self.document.name)
                if self.document
                else self.url.rsplit("/", 1)[-1] if self.url else ""
            )
        )

    def link(self):
        return self.document.url if self.document else self.url

    def full_link(self, request=None):
        return get_full_url(self.document.url, request) if self.document else self.url

    def can_be_embedded(self):
        return any([self.link().lower().endswith(ext) for ext in supported_embedded_extensions])

    def __str__(self):
        return self.filename()

    def clean(self):
        if not self.document and not self.url:
            raise ValidationError({"document": "Either document or URL should be provided."})
        elif self.document and self.url:
            raise ValidationError({"document": "Choose either document or URL but not both."})

    class Meta:
        ordering = ["display_order", "-uploaded_at"]
        abstract = True


# These two auto-delete documents from filesystem when they are unneeded:
@receiver(models.signals.post_delete)
def auto_delete_file_on_document_delete(sender, instance: BaseDocumentModel, **kwargs):
    if not issubclass(sender, BaseDocumentModel):
        return
    """	Deletes file from filesystem when corresponding object is deleted.	"""
    if instance.document:
        if os.path.isfile(instance.document.path):
            os.remove(instance.document.path)


@receiver(models.signals.pre_save)
def auto_delete_file_on_document_change(sender, instance: BaseDocumentModel, **kwargs):
    if not issubclass(sender, BaseDocumentModel):
        return
    """	Deletes old file from filesystem when corresponding object is updated with new file. """
    if not instance.pk:
        return False

    model_class = type(instance)

    try:
        old_file = model_class.objects.get(pk=instance.pk).document
    except model_class.DoesNotExist:
        return False

    new_file = instance.document
    if old_file and not old_file == new_file:
        if os.path.isfile(old_file.path):
            os.remove(old_file.path)


class ReservationItemType(Enum):
    TOOL = "tool"
    AREA = "area"
    NONE = ""

    def get_object_class(self):
        if self == ReservationItemType.AREA:
            return Area
        elif self == ReservationItemType.TOOL:
            return Tool

    @staticmethod
    def values():
        return list(map(lambda c: c.value, ReservationItemType))

    @classmethod
    def _missing_(cls, value):
        return ReservationItemType.NONE

    @classmethod
    def from_item(cls, item):
        if isinstance(item, Tool):
            return ReservationItemType.TOOL
        elif isinstance(item, Area):
            return ReservationItemType.AREA
        else:
            return ReservationItemType.NONE


class EmailNotificationType(object):
    OFF = 0
    BOTH_EMAILS = 1
    MAIN_EMAIL = 2
    ALTERNATE_EMAIL = 3
    Choices = (
        (BOTH_EMAILS, "Both emails"),
        (MAIN_EMAIL, "Main email only"),
        (ALTERNATE_EMAIL, "Alternate email only"),
        (OFF, "Off"),
    )

    @classmethod
    def on_choices(cls):
        return [(choice[0], choice[1]) for choice in cls.Choices if choice[0] not in [cls.OFF, cls.ALTERNATE_EMAIL]]


class RequestStatus(object):
    PENDING = 0
    APPROVED = 1
    DENIED = 2
    EXPIRED = 3
    Choices = (
        (PENDING, "Pending"),
        (APPROVED, "Approved"),
        (DENIED, "Denied"),
        (EXPIRED, "Expired"),
    )

    @classmethod
    def choices_without_expired(cls):
        return [(choice[0], choice[1]) for choice in cls.Choices if choice[0] not in [cls.EXPIRED]]


class UserPreferences(BaseModel):
    attach_created_reservation = models.BooleanField(
        "created_reservation_invite",
        default=False,
        help_text="Whether or not to send a calendar invitation when creating a new reservation",
    )
    attach_cancelled_reservation = models.BooleanField(
        "cancelled_reservation_invite",
        default=False,
        help_text="Whether or not to send a calendar invitation when cancelling a reservation",
    )
    display_new_buddy_request_notification = models.BooleanField(
        "new_buddy_request_notification",
        default=True,
        help_text="Whether or not to notify the user of new buddy requests (via unread badges)",
    )
    email_new_buddy_request_reply = models.BooleanField(
        "email_new_buddy_request_reply",
        default=True,
        help_text="Whether or not to email the user of replies on buddy request he commented on",
    )
    email_new_adjustment_request_reply = models.BooleanField(
        "email_new_adjustment_request_reply",
        default=True,
        help_text="Whether or not to email the user of replies on adjustment request he commented on",
    )
    staff_status_view = models.CharField(
        "staff_status_view",
        max_length=CHAR_FIELD_SMALL_LENGTH,
        default="day",
        choices=[("day", "Day"), ("week", "Week"), ("month", "Month")],
        help_text="Preferred view for staff status page",
    )
    email_alternate = models.EmailField(null=True, blank=True)
    # Sort by the notifications that cannot be turned off first
    email_send_reservation_emails = models.PositiveIntegerField(
        default=EmailNotificationType.BOTH_EMAILS,
        choices=EmailNotificationType.on_choices(),
        help_text="Reservation emails",
    )
    email_send_buddy_request_replies = models.PositiveIntegerField(
        default=EmailNotificationType.BOTH_EMAILS,
        choices=EmailNotificationType.on_choices(),
        help_text="Buddy request replies",
    )
    email_send_access_request_updates = models.PositiveIntegerField(
        default=EmailNotificationType.BOTH_EMAILS,
        choices=EmailNotificationType.on_choices(),
        help_text="Access request updates",
    )
    email_send_adjustment_request_updates = models.PositiveIntegerField(
        default=EmailNotificationType.BOTH_EMAILS,
        choices=EmailNotificationType.on_choices(),
        help_text="Adjustment request updates",
    )
    email_send_broadcast_emails = models.PositiveIntegerField(
        default=EmailNotificationType.BOTH_EMAILS,
        choices=EmailNotificationType.on_choices(),
        help_text="Broadcast emails",
    )
    email_send_task_updates = models.PositiveIntegerField(
        default=EmailNotificationType.BOTH_EMAILS, choices=EmailNotificationType.on_choices(), help_text="Task updates"
    )
    email_send_access_expiration_emails = models.PositiveIntegerField(
        default=EmailNotificationType.BOTH_EMAILS,
        choices=EmailNotificationType.on_choices(),
        help_text="Access expiration reminders",
    )
    email_send_tool_qualification_expiration_emails = models.PositiveIntegerField(
        default=EmailNotificationType.BOTH_EMAILS,
        choices=EmailNotificationType.on_choices(),
        help_text="Tool qualification expiration reminders",
    )
    email_send_wait_list_notification_emails = models.PositiveIntegerField(
        default=EmailNotificationType.BOTH_EMAILS,
        choices=EmailNotificationType.on_choices(),
        help_text="Tool wait list notification",
    )
    email_send_usage_reminders = models.PositiveIntegerField(
        default=EmailNotificationType.BOTH_EMAILS, choices=EmailNotificationType.Choices, help_text="Usage reminders"
    )
    email_send_reservation_reminders = models.PositiveIntegerField(
        default=EmailNotificationType.BOTH_EMAILS,
        choices=EmailNotificationType.Choices,
        help_text="Reservation reminders",
    )
    email_send_reservation_ending_reminders = models.PositiveIntegerField(
        default=EmailNotificationType.BOTH_EMAILS,
        choices=EmailNotificationType.Choices,
        help_text="Reservation ending reminders",
    )
    recurring_charges_reminder_days = models.CharField(
        null=True,
        blank=True,
        default="60,7",
        max_length=CHAR_FIELD_MEDIUM_LENGTH,
        help_text="The number of days to send a reminder before a recurring charge is due. A comma-separated list can be used for multiple reminders.",
    )
    create_reservation_confirmation_override = models.BooleanField(
        default=False,
        help_text="Override default create reservation confirmation setting",
    )
    change_reservation_confirmation_override = models.BooleanField(
        default=False,
        help_text="Override default move/resize reservation confirmation setting",
    )
    email_send_recurring_charges_reminder_emails = models.PositiveIntegerField(
        default=EmailNotificationType.BOTH_EMAILS,
        choices=EmailNotificationType.Choices,
        help_text="Recurring charges reminders",
    )
    tool_freed_time_notifications = models.ManyToManyField(
        "Tool", blank=True, help_text="Tools to receive notification when reservation time is freed."
    )
    tool_freed_time_notifications_min_time = models.PositiveIntegerField(
        default=120, help_text="Minimum amount of minutes freed to receive a notification."
    )
    tool_freed_time_notifications_max_future_days = models.PositiveIntegerField(
        default=7, help_text="Maximum number of days in the future to receive a notification for."
    )
    tool_task_notifications = models.ManyToManyField(
        "Tool",
        related_name="+",
        blank=True,
        help_text="Tools to see maintenance records and receive task notifications for. If empty all notifications will be received.",
    )

    def get_recurring_charges_days(self) -> List[int]:
        return [
            int(days)
            for days in self.recurring_charges_reminder_days.split(",")
            if self.recurring_charges_reminder_days
        ]

    def __str__(self):
        return f"{self.user.username}'s preferences"

    class Meta:
        verbose_name = "User preferences"
        verbose_name_plural = "User preferences"


class UserType(BaseCategory):
    pass


class ProjectDiscipline(BaseCategory):
    name = models.CharField(max_length=CHAR_FIELD_MEDIUM_LENGTH, unique=True, help_text="The name of the discipline")


class PhysicalAccessLevel(BaseModel):
    class Schedule(object):
        ALWAYS = 0
        WEEKDAYS = 1
        WEEKENDS = 2
        Choices = (
            (ALWAYS, "Anytime"),
            (WEEKDAYS, "Weekdays"),
            (WEEKENDS, "Weekends"),
        )

    name = models.CharField(max_length=CHAR_FIELD_SMALL_LENGTH)
    area = TreeForeignKey("Area", on_delete=models.CASCADE)
    schedule = models.IntegerField(choices=Schedule.Choices)
    weekdays_start_time = models.TimeField(
        default=datetime.time(hour=7), null=True, blank=True, help_text="The weekday access start time"
    )
    weekdays_end_time = models.TimeField(
        default=datetime.time(hour=0), null=True, blank=True, help_text="The weekday access end time"
    )
    allow_staff_access = models.BooleanField(
        blank=False,
        null=False,
        default=False,
        help_text="Check this box to allow access to Staff and User Office members without explicitly granting them access",
    )
    allow_user_request = models.BooleanField(
        blank=False,
        null=False,
        default=False,
        help_text='Check this box to allow users to request this access temporarily in "Access requests"',
    )

    def get_schedule_display_with_times(self):
        if self.schedule == self.Schedule.ALWAYS or self.schedule == self.Schedule.WEEKENDS:
            return self.get_schedule_display()
        else:
            return (
                self.get_schedule_display() + " " + format_daterange(self.weekdays_start_time, self.weekdays_end_time)
            )

    get_schedule_display_with_times.short_description = "Schedule"

    def accessible_at(self, time):
        return self.accessible(time)

    def accessible(self, time: datetime = None):
        if time is not None:
            accessible_time = timezone.localtime(time)
        else:
            accessible_time = timezone.localtime(timezone.now())
        # First deal with exceptions
        if self.ongoing_closure_time(accessible_time):
            return False
        # Then look at the actual allowed schedule
        saturday = 6
        sunday = 7
        if self.schedule == self.Schedule.ALWAYS:
            return True
        elif self.schedule == self.Schedule.WEEKDAYS:
            if accessible_time.isoweekday() == saturday or accessible_time.isoweekday() == sunday:
                return False
            current_time = accessible_time.time()
            if self.weekdays_start_time <= self.weekdays_end_time:
                """Range is something like 6am-6pm"""
                if self.weekdays_start_time <= current_time <= self.weekdays_end_time:
                    return True
            else:
                """Range is something like 6pm-6am"""
                if self.weekdays_start_time <= current_time or current_time <= self.weekdays_end_time:
                    return True
        elif self.schedule == self.Schedule.WEEKENDS:
            if accessible_time.isoweekday() == saturday or accessible_time.isoweekday() == sunday:
                return True
        return False

    def ongoing_closure_time(self, time: datetime = None):
        if time is not None:
            accessible_time = timezone.localtime(time)
        else:
            accessible_time = timezone.localtime(timezone.now())
        return ClosureTime.objects.filter(
            closure__physical_access_levels__in=[self], start_time__lte=accessible_time, end_time__gt=accessible_time
        ).first()

    def display_value_for_select(self):
        return f"{str(self.area.name)} ({self.get_schedule_display_with_times()})"

    def __str__(self):
        return str(self.name)

    class Meta:
        ordering = ["name"]


class TemporaryPhysicalAccess(BaseModel):
    user = models.ForeignKey("User", on_delete=models.CASCADE)
    physical_access_level = models.ForeignKey(PhysicalAccessLevel, on_delete=models.CASCADE)
    start_time = models.DateTimeField(help_text="The start of the temporary access")
    end_time = models.DateTimeField(help_text="The end of the temporary access")

    def get_schedule_display_with_times(self):
        return f"Temporary {self.physical_access_level.get_schedule_display_with_times()} {format_daterange(self.start_time, self.end_time, dt_format='SHORT_DATETIME_FORMAT')}"

    get_schedule_display_with_times.short_description = "Schedule"

    def accessible_at(self, time):
        return self.accessible(time)

    def accessible(self, time: datetime = None):
        if time is not None:
            accessible_time = timezone.localtime(time)
        else:
            accessible_time = timezone.localtime(timezone.now())
        return (
            self.physical_access_level.accessible(accessible_time)
            and self.start_time <= accessible_time <= self.end_time
        )

    def ongoing_closure_time(self, time: datetime = None):
        return self.physical_access_level.ongoing_closure_time(time)

    def display(self):
        return f"Temporary physical access of the '{self.physical_access_level.name}' for {self.user.get_full_name()} {format_daterange(self.start_time, self.end_time)}"

    def clean(self):
        if self.end_time and self.start_time and self.end_time <= self.start_time:
            raise ValidationError({"end_time": "The end time must be later than the start time"})

    class Meta:
        ordering = ["-end_time"]
        verbose_name_plural = "TemporaryPhysicalAccess"


class TemporaryPhysicalAccessRequest(BaseModel):
    creation_time = models.DateTimeField(auto_now_add=True, help_text="The date and time when the request was created.")
    creator = models.ForeignKey("User", related_name="access_requests_created", on_delete=models.CASCADE)
    last_updated = models.DateTimeField(auto_now=True, help_text="The last time this request was modified.")
    last_updated_by = models.ForeignKey(
        "User",
        null=True,
        blank=True,
        related_name="access_requests_updated",
        help_text="The last user who modified this request.",
        on_delete=models.SET_NULL,
    )
    physical_access_level = models.ForeignKey(PhysicalAccessLevel, on_delete=models.CASCADE)
    description = models.TextField(null=True, blank=True, help_text="The description of the request.")
    start_time = models.DateTimeField(help_text="The requested time for the access to start.")
    end_time = models.DateTimeField(help_text="The requested time for the access to end.")
    other_users = models.ManyToManyField("User", blank=True, help_text="Select the other users requesting access.")
    status = models.IntegerField(choices=RequestStatus.Choices, default=RequestStatus.PENDING)
    reviewer = models.ForeignKey(
        "User", null=True, blank=True, related_name="access_requests_reviewed", on_delete=models.CASCADE
    )
    deleted = models.BooleanField(
        default=False, help_text="Indicates the request has been deleted and won't be shown anymore."
    )

    def creator_and_other_users(self) -> Set[User]:
        result = {self.creator}
        result.update(self.other_users.all())
        return result

    def reviewers(self) -> QuerySetType[User]:
        # Create the list of users to notify/show request to. If the physical access request area's
        # list of reviewers is empty, send/show to all facility managers
        facility_managers = User.objects.filter(is_active=True, is_facility_manager=True)
        area_reviewers = self.physical_access_level.area.access_request_reviewers.filter(is_active=True)
        return area_reviewers or facility_managers

    def clean(self):
        if self.start_time and self.end_time and self.end_time <= self.start_time:
            raise ValidationError({"end_time": "The end time must be later than the start time"})

    class Meta:
        ordering = ["-creation_time"]


class Closure(BaseModel):
    name = models.CharField(
        max_length=CHAR_FIELD_MEDIUM_LENGTH,
        help_text="The name of this closure, that will be displayed as the policy problem and alert (if applicable).",
    )
    alert_days_before = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Enter the number of days before the closure when an alert should automatically be created. Leave blank for no alert.",
    )
    alert_template = models.TextField(
        null=True,
        blank=True,
        help_text=mark_safe(
            "The template to create the alert with. The following variables are provided (when applicable): <b>name</b>, <b>start_time</b>, <b>end_time</b>, <b>areas</b>."
        ),
    )
    notify_managers_last_occurrence = models.BooleanField(
        default=True, help_text="Check this box to notify facility managers on the last occurrence of this closure."
    )
    staff_absent = models.BooleanField(
        verbose_name="Staff absent entire day",
        default=True,
        help_text="Check this box and all staff members will be marked absent during this closure in staff status.",
    )
    physical_access_levels = models.ManyToManyField(
        "PhysicalAccessLevel", blank=True, help_text="Select access levels this closure applies to."
    )

    def __str__(self):
        return str(self.name)

    class Meta:
        ordering = ["name"]


class ClosureTime(BaseModel):
    closure = models.ForeignKey(Closure, on_delete=models.CASCADE)
    start_time = models.DateTimeField(help_text="The start date and time of the closure")
    end_time = models.DateTimeField(help_text="The end date and time of the closure")

    def alert_contents(self, access_levels=Q()):
        if access_levels == Q():
            access_levels = self.closure.physical_access_levels.all()
        areas = Area.objects.filter(id__in=distinct_qs_value_list(access_levels, "area"))
        dictionary = {
            "closure_time": self,
            "name": self.closure.name,
            "staff_absent": self.closure.staff_absent,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "areas": areas,
        }
        contents = (
            render_email_template(self.closure.alert_template, dictionary) if self.closure.alert_template else None
        )
        return contents

    def clean(self):
        if self.start_time and self.end_time and self.end_time <= self.start_time:
            raise ValidationError({"end_time": "The end time must be later than the start time"})

    def __str__(self):
        return format_daterange(self.start_time, self.end_time)

    class Meta:
        ordering = ["-start_time"]


class PhysicalAccessType(object):
    DENY = False
    ALLOW = True
    Choices = (
        (False, "Deny"),
        (True, "Allow"),
    )


class PhysicalAccessLog(BaseModel):
    user = models.ForeignKey("User", on_delete=models.CASCADE)
    door = models.ForeignKey("Door", on_delete=models.CASCADE)
    time = models.DateTimeField()
    result = models.BooleanField(choices=PhysicalAccessType.Choices, default=None)
    details = models.TextField(
        null=True,
        blank=True,
        help_text="Any details that should accompany the log entry. For example, the reason physical access was denied.",
    )

    class Meta:
        ordering = ["-time"]


class SafetyTraining(BaseCategory):
    pass


class OnboardingPhase(BaseCategory):
    pass


class User(BaseModel, PermissionsMixin):
    # Personal information:
    username = models.CharField(max_length=CHAR_FIELD_SMALL_LENGTH, unique=True)
    first_name = models.CharField(max_length=CHAR_FIELD_SMALL_LENGTH)
    last_name = models.CharField(max_length=CHAR_FIELD_SMALL_LENGTH)
    email = models.EmailField(verbose_name="email address")
    type = models.ForeignKey(UserType, null=True, blank=True, on_delete=models.SET_NULL)
    domain = models.CharField(
        max_length=CHAR_FIELD_SMALL_LENGTH,
        blank=True,
        help_text="The Active Directory domain that the account resides on",
    )
    onboarding_phases = models.ManyToManyField(OnboardingPhase, blank=True)
    safety_trainings = models.ManyToManyField(SafetyTraining, blank=True)
    notes = models.TextField(null=True, blank=True)

    # Physical access fields
    badge_number = models.CharField(
        null=True,
        blank=True,
        unique=True,
        max_length=50,
        help_text="The badge number associated with this user. This number must correctly correspond to a user in order for the tablet-login system (in the lobby) to work properly.",
    )
    access_expiration = models.DateField(
        verbose_name="active access expiration",
        blank=True,
        null=True,
        help_text="The user will lose all access rights after this date. Typically this is used to ensure that safety training has been completed by the user every year.",
    )
    physical_access_levels = models.ManyToManyField("PhysicalAccessLevel", blank=True)

    # Permissions
    is_active = models.BooleanField(
        "active account",
        default=True,
        help_text="Designates whether this user can log in. Unselect this instead of deleting accounts.",
    )
    is_staff = models.BooleanField(
        "staff",
        default=False,
        help_text="Designates this user as technical staff. Technical staff can start remote projects, check maintenance, change configuration, train users etc.",
    )
    is_user_office = models.BooleanField(
        "user office",
        default=False,
        help_text="Designates this user as part of the User Office. User Office staff can create and manage users and projects, charge supplies, check usage etc.",
    )
    is_accounting_officer = models.BooleanField(
        "accounting officer",
        default=False,
        help_text="Designates this user as Accounting officer. Accounting officers can manage projects, view user details, and check usage/billing.",
    )
    is_service_personnel = models.BooleanField(
        "service personnel",
        default=False,
        help_text="Designates this user as service personnel. Service personnel can operate qualified tools without a reservation even when they are shutdown or during an outage and can access authorized areas without a reservation.",
    )
    is_technician = models.BooleanField(
        "technician",
        default=False,
        help_text="Specifies how to bill staff time for this user. When checked, customers are billed at technician rates.",
    )
    is_facility_manager = models.BooleanField(
        "facility manager",
        default=False,
        help_text="Designates this user as facility manager. Facility managers receive updates on all reported problems in the facility and also review access and adjustment requests.",
    )
    is_superuser = models.BooleanField(
        "administrator",
        default=False,
        help_text="Designates that this user has all permissions without explicitly assigning them.",
    )
    training_required = models.BooleanField(
        "facility rules tutorial required",
        default=True,
        help_text="When selected, the user is blocked from all reservation and tool usage capabilities.",
    )
    groups = models.ManyToManyField(
        Group,
        blank=True,
        help_text="The groups this user belongs to. A user will get all permissions granted to each of his/her group.",
    )
    user_permissions = models.ManyToManyField(Permission, blank=True, help_text="Specific permissions for this user.")

    # Important dates
    date_joined = models.DateTimeField(default=timezone.now)
    last_login = models.DateTimeField(null=True, blank=True)

    # Facility information:
    qualifications = models.ManyToManyField(
        "Tool", blank=True, help_text="Select the tools that the user is qualified to use.", through="Qualification"
    )
    projects = models.ManyToManyField(
        "Project", blank=True, help_text="Select the projects that this user is currently working on."
    )
    managed_projects = models.ManyToManyField(
        "Project", related_name="manager_set", blank=True, help_text="Select the projects that this user is a PI for."
    )

    # Preferences
    preferences: UserPreferences = models.OneToOneField(UserPreferences, null=True, on_delete=models.SET_NULL)

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS = ["first_name", "last_name", "email"]
    objects = UserManager()

    def natural_key(self):
        return (self.get_username(),)

    def clean(self):
        from NEMO.views.customization import UserCustomization

        user_type_required = UserCustomization.get_bool("user_type_required")
        if user_type_required and UserType.objects.exists() and not self.type_id:
            raise ValidationError({"type": _("This field is required.")})
        username_pattern = getattr(settings, "USERNAME_REGEX", None)
        if self.username:
            if username_pattern and not match(username_pattern, self.username):
                raise ValidationError({"username": _("Invalid username format")})
            username_taken = User.objects.filter(username__iexact=self.username)
            if self.pk:
                username_taken = username_taken.exclude(pk=self.pk)
            if username_taken.exists():
                raise ValidationError({"username": _("This username has already been taken")})
        if self.is_staff and self.is_service_personnel:
            raise ValidationError(
                {
                    "is_staff": _("A user cannot be both staff and service personnel. Please choose one or the other."),
                    "is_service_personnel": _(
                        "A user cannot be both staff and service personnel. Please choose one or the other."
                    ),
                }
            )

    def has_access_expired(self) -> bool:
        return self.access_expiration and self.access_expiration < datetime.date.today()

    def check_password(self, raw_password):
        return False

    @property
    def is_authenticated(self):
        return True

    @property
    def is_anonymous(self):
        return False

    @property
    def is_tool_superuser(self):
        return self.superuser_for_tools.exists()

    @property
    def is_project_pi(self):
        return self.managed_projects.exists()

    @property
    def is_any_part_of_staff(self):
        return any(
            [
                self.is_staff,
                self.is_accounting_officer,
                self.is_user_office,
                self.is_facility_manager,
                self.is_superuser,
            ]
        )

    def get_username(self):
        return self.username

    def has_usable_password(self):
        return False

    def set_unusable_password(self):
        pass

    def get_emails(self, email_notification=EmailNotificationType.MAIN_EMAIL) -> List[str]:
        emails = []
        if email_notification in [EmailNotificationType.BOTH_EMAILS, EmailNotificationType.MAIN_EMAIL]:
            emails.append(self.email)
        if (
            self.get_preferences().email_alternate
            and email_notification in [EmailNotificationType.BOTH_EMAILS, EmailNotificationType.ALTERNATE_EMAIL]
            and self.preferences.email_alternate not in emails
        ):
            emails.append(self.preferences.email_alternate)
        return emails

    def email_user(
        self,
        subject,
        message,
        from_email,
        cc=None,
        attachments=None,
        email_notification=EmailNotificationType.MAIN_EMAIL,
        email_category: EmailCategory = EmailCategory.GENERAL,
    ):
        """Sends an email to this user."""
        send_mail(
            subject=subject,
            content=message,
            from_email=from_email,
            to=self.get_emails(email_notification),
            cc=cc,
            attachments=attachments,
            email_category=email_category,
        )

    def get_full_name(self):
        return self.get_name() + " (" + self.username + ")"

    def get_short_name(self):
        return self.first_name

    def get_name(self):
        return self.first_name + " " + self.last_name

    def get_initials(self):
        first_name_initial = self.first_name[0] if self.first_name else ""
        last_name_initial = self.last_name[0] if self.last_name else ""
        return first_name_initial + last_name_initial

    def accessible_access_levels(self):
        if not self.is_staff and not self.is_user_office:
            return self.physical_access_levels.all()
        else:
            return PhysicalAccessLevel.objects.filter(
                Q(id__in=self.physical_access_levels.all()) | Q(allow_staff_access=True)
            ).distinct()

    def accessible_access_levels_for_area(self, area) -> List[Union[PhysicalAccessLevel, TemporaryPhysicalAccess]]:
        """
        Return access levels for the area or parent areas.
        This means when checking access for area1, having access to its parent area grants access to area1
        """
        return list(self.accessible_access_levels().filter(area__in=area.get_ancestors(include_self=True))) + list(
            self.temporaryphysicalaccess_set.filter(
                end_time__gt=timezone.now(), physical_access_level__area__in=area.get_ancestors(include_self=True)
            )
        )

    def accessible_areas(self):
        """Returns accessible leaf node areas for this user, including descendants"""
        return Area.objects.filter(
            id__in=[
                leaf_descendant.id
                for access in self.accessible_access_levels()
                for leaf_descendant in access.area.get_descendants(include_self=True)
                if leaf_descendant.is_leaf_node()
            ]
        ).distinct()

    def in_area(self) -> bool:
        return AreaAccessRecord.objects.filter(customer=self, staff_charge=None, end=None).exists()

    def area_access_record(self) -> Optional[AreaAccessRecord]:
        try:
            return AreaAccessRecord.objects.get(customer=self, staff_charge=None, end=None)
        except AreaAccessRecord.DoesNotExist:
            return None

    def is_logged_in_area_outside_authorized_schedule(self) -> bool:
        # Checks whether a user is logged in past his allowed schedule time
        access_record = self.area_access_record()
        if access_record:
            area = access_record.area
            physical_access_exist = PhysicalAccessLevel.objects.filter(area=area, user__isnull=False).exists()
            if physical_access_exist:
                return not any(
                    [access_level.accessible() for access_level in self.accessible_access_levels_for_area(area)]
                )

    def is_logged_in_area_without_reservation(self) -> bool:
        access_record = self.area_access_record()
        if access_record:
            area = access_record.area
            if area.requires_reservation:
                end_time = (
                    timezone.now()
                    if not area.logout_grace_period
                    else timezone.now() - timedelta(minutes=area.logout_grace_period)
                )
                return not Reservation.objects.filter(
                    cancelled=False,
                    missed=False,
                    shortened=False,
                    area=area,
                    user=self,
                    start__lte=timezone.now(),
                    end__gte=end_time,
                ).exists()
        return False

    def billing_to_project(self):
        access_record = self.area_access_record()
        if access_record is None:
            return None
        else:
            return access_record.project

    def active_project_count(self):
        return self.active_projects().count()

    def active_projects(self):
        return self.projects.filter(active=True, account__active=True)

    def charging_staff_time(self) -> bool:
        return StaffCharge.objects.filter(staff_member=self.id, end=None).exists()

    def get_staff_charge(self):
        try:
            return StaffCharge.objects.get(staff_member=self.id, end=None)
        except StaffCharge.DoesNotExist:
            return None

    def get_preferences(self) -> UserPreferences:
        if not self.preferences:
            default_reservation_preferences = getattr(settings, "USER_RESERVATION_PREFERENCES_DEFAULT", False)
            self.preferences = UserPreferences.objects.create(
                attach_cancelled_reservation=default_reservation_preferences,
                attach_created_reservation=default_reservation_preferences,
            )
            self.save()
        return self.preferences

    def get_contact_info_html(self):
        if hasattr(self, "contactinformation"):
            content = escape(
                loader.render_to_string(
                    "snippets/contact_person.html", {"person": self.contactinformation, "email_form": True}
                )
            )
            return f'<a href="javascript:;" data-title="{content}" data-placement="bottom" class="contact-info-tooltip info-tooltip-container"><span class="glyphicon glyphicon-send small-icon"></span>{self.contactinformation.name}</a>'
        else:
            email_url = reverse("get_email_form_for_user", kwargs={"user_id": self.id})
            content = escape(
                f'<h4 style="margin-top:0; text-align: center">{self.get_name()}</h4>Email: <a href="{email_url}" target="_blank">{self.email}</a><br>'
            )
            return f'<a href="javascript:;" data-title="{content}" data-placement="bottom" class="contact-info-tooltip info-tooltip-container"><span class="glyphicon glyphicon-send small-icon"></span>{self.get_name()}</a>'

    def has_perm(self, perm, obj=None):
        # By default we don't use the actual object, similar to django admin
        general_permission = super().has_perm(perm)
        if general_permission:
            return True
        # For charges, the reviewer of an adjustment request for that charge can also edit it
        if obj and issubclass(type(obj), BillableItemMixin):
            # If there is an approved adjustment request for this charge, check if the user is a reviewer
            adjustment_request: AdjustmentRequest = AdjustmentRequest.objects.filter(
                status=RequestStatus.APPROVED,
                deleted=False,
                item_id=obj.id,
                item_type=ContentType.objects.get_for_model(obj),
            ).first()
            if adjustment_request:
                return self in adjustment_request.reviewers()
        return general_permission

    @classmethod
    def get_email_field_name(cls):
        return "email"

    class Meta:
        ordering = ["first_name"]
        permissions = (
            ("trigger_timed_services", "Can trigger timed services"),
            ("use_billing_api", "Can use billing API"),
            ("kiosk", "Kiosk services"),
            ("can_impersonate_users", "Can impersonate other users"),
        )

    def __str__(self):
        return self.get_full_name()


class UserDocuments(BaseDocumentModel):
    user = models.ForeignKey(User, related_name="user_documents", on_delete=models.CASCADE)

    def get_filename_upload(self, filename):
        from django.template.defaultfilters import slugify

        username = slugify(self.user.username)
        return f"user_documents/{username}/{filename}"

    class Meta(BaseDocumentModel.Meta):
        verbose_name_plural = "User documents"


class Tool(SerializationByNameModel):
    class OperationMode(object):
        REGULAR = 0
        WAIT_LIST = 1
        HYBRID = 2
        Choices = ((REGULAR, "Regular"), (WAIT_LIST, "Wait List"), (HYBRID, "Hybrid"))

    name = models.CharField(max_length=CHAR_FIELD_SMALL_LENGTH, unique=True)
    parent_tool = models.ForeignKey(
        "Tool",
        related_name="tool_children_set",
        null=True,
        blank=True,
        help_text="Select a parent tool to allow alternate usage",
        on_delete=models.CASCADE,
    )
    visible = models.BooleanField(default=True, help_text="Specifies whether this tool is visible to users.")
    _description = models.TextField(
        db_column="description", null=True, blank=True, help_text="HTML syntax could be used"
    )
    _serial = models.CharField(
        db_column="serial", null=True, blank=True, max_length=CHAR_FIELD_SMALL_LENGTH, help_text="Serial Number"
    )
    _image = models.ImageField(
        db_column="image",
        upload_to=get_tool_image_filename,
        blank=True,
        help_text="An image that represent the tool. Maximum width and height are 500px",
    )
    _tool_calendar_color = models.CharField(
        db_column="tool_calendar_color",
        max_length=9,
        default="#33ad33",
        help_text="Color for tool reservations in calendar overviews",
        validators=[color_hex_validator],
    )
    _category = models.CharField(
        db_column="category",
        null=True,
        blank=True,
        max_length=CHAR_FIELD_LARGE_LENGTH,
        help_text='Create sub-categories using slashes. For example "Category 1/Sub-category 1".',
    )
    _operational = models.BooleanField(
        db_column="operational",
        default=False,
        help_text="Marking the tool non-operational will prevent users from using the tool.",
    )
    # Tool permissions
    _primary_owner = models.ForeignKey(
        User,
        db_column="primary_owner_id",
        null=True,
        blank=True,
        related_name="primary_tool_owner",
        help_text="The staff member who is responsible for administration of this tool.",
        on_delete=models.PROTECT,
    )
    _backup_owners = models.ManyToManyField(
        User,
        db_table="NEMO_tool_backup_owners",
        blank=True,
        related_name="backup_for_tools",
        help_text="Alternate staff members who are responsible for administration of this tool when the primary owner is unavailable.",
    )
    _superusers = models.ManyToManyField(
        User,
        db_table="NEMO_tool_superusers",
        blank=True,
        related_name="superuser_for_tools",
        help_text="Superusers who can train users on this tool.",
    )
    _adjustment_request_reviewers = models.ManyToManyField(
        User,
        db_table="NEMO_tool_adjustment_request_reviewers",
        blank=True,
        related_name="adjustment_request_reviewer_on_tools",
        help_text="Users who can approve/deny adjustment requests for this tool. Defaults to facility managers if left blank.",
    )
    # Extra info
    _location = models.CharField(db_column="location", null=True, blank=True, max_length=CHAR_FIELD_SMALL_LENGTH)
    _phone_number = models.CharField(
        db_column="phone_number", null=True, blank=True, max_length=CHAR_FIELD_SMALL_LENGTH
    )
    _notification_email_address = models.EmailField(
        db_column="notification_email_address",
        blank=True,
        null=True,
        help_text="Messages that relate to this tool (such as comments, problems, and shutdowns) will be forwarded to this email address. This can be a normal email address or a mailing list address.",
    )
    _interlock = models.OneToOneField(
        "Interlock", db_column="interlock_id", blank=True, null=True, on_delete=models.SET_NULL
    )
    _qualifications_never_expire = models.BooleanField(
        default=False,
        db_column="qualifications_never_expire",
        help_text="Check this box if qualifications for this tool should never expire (even if the tool qualification expiration feature is enabled).",
    )
    # Policy fields:
    _requires_area_access = TreeForeignKey(
        "Area",
        db_column="requires_area_access_id",
        null=True,
        blank=True,
        help_text="Indicates that this tool is physically located in a billable area and requires an active area access record in order to be operated.",
        on_delete=models.PROTECT,
    )
    _ask_to_leave_area_when_done_using = models.BooleanField(
        default=False,
        db_column="ask_to_leave_area_when_done_using",
        help_text="Check this box to ask the user if they want to log out of the area when they are done using the tool.",
    )
    _grant_physical_access_level_upon_qualification = models.ForeignKey(
        "PhysicalAccessLevel",
        db_column="grant_physical_access_level_upon_qualification_id",
        null=True,
        blank=True,
        help_text="The designated physical access level is granted to the user upon qualification for this tool.",
        on_delete=models.PROTECT,
    )
    _grant_badge_reader_access_upon_qualification = models.CharField(
        db_column="grant_badge_reader_access_upon_qualification",
        max_length=CHAR_FIELD_SMALL_LENGTH,
        null=True,
        blank=True,
        help_text="Badge reader access is granted to the user upon qualification for this tool.",
    )
    _reservation_horizon = models.PositiveIntegerField(
        db_column="reservation_horizon",
        default=14,
        null=True,
        blank=True,
        help_text="Users may create reservations this many days in advance. Leave this field blank to indicate that no reservation horizon exists for this tool.",
    )
    _minimum_usage_block_time = models.PositiveIntegerField(
        db_column="minimum_usage_block_time",
        null=True,
        blank=True,
        help_text="The minimum amount of time (in minutes) that a user must reserve this tool for a single reservation. Leave this field blank to indicate that no minimum usage block time exists for this tool.",
    )
    _maximum_usage_block_time = models.PositiveIntegerField(
        db_column="maximum_usage_block_time",
        null=True,
        blank=True,
        help_text="The maximum amount of time (in minutes) that a user may reserve this tool for a single reservation. Leave this field blank to indicate that no maximum usage block time exists for this tool.",
    )
    _maximum_reservations_per_day = models.PositiveIntegerField(
        db_column="maximum_reservations_per_day",
        null=True,
        blank=True,
        help_text="The maximum number of reservations a user may make per day for this tool.",
    )
    _minimum_time_between_reservations = models.PositiveIntegerField(
        db_column="minimum_time_between_reservations",
        null=True,
        blank=True,
        help_text="The minimum amount of time (in minutes) that the same user must have between any two reservations for this tool.",
    )
    _maximum_future_reservation_time = models.PositiveIntegerField(
        db_column="maximum_future_reservation_time",
        null=True,
        blank=True,
        help_text="The maximum amount of time (in minutes) that a user may reserve from the current time onwards.",
    )
    _missed_reservation_threshold = models.PositiveIntegerField(
        db_column="missed_reservation_threshold",
        null=True,
        blank=True,
        help_text='The amount of time (in minutes) that a tool reservation may go unused before it is automatically marked as "missed" and hidden from the calendar. Usage can be from any user, regardless of who the reservation was originally created for. The cancellation process is triggered by a timed job on the web server.',
    )
    _max_delayed_logoff = models.PositiveIntegerField(
        null=True,
        blank=True,
        db_column="max_delayed_logoff",
        help_text='[Optional] Maximum delay in minutes that users may enter upon logging off before another user may use the tool. Some tools require "spin-down" or cleaning time after use. Leave blank to disable.',
    )
    _pre_usage_questions = models.TextField(
        db_column="pre_usage_questions",
        null=True,
        blank=True,
        help_text="Before using a tool, questions can be asked. This field will only accept JSON format",
    )
    _post_usage_questions = models.TextField(
        db_column="post_usage_questions",
        null=True,
        blank=True,
        help_text="Upon logging off a tool, questions can be asked such as how much consumables were used by the user. This field will only accept JSON format",
    )
    _policy_off_between_times = models.BooleanField(
        db_column="policy_off_between_times",
        default=False,
        help_text="Check this box to disable policy rules every day between the given times",
    )
    _policy_off_start_time = models.TimeField(
        db_column="policy_off_start_time",
        null=True,
        blank=True,
        help_text="The start time when policy rules should NOT be enforced",
    )
    _policy_off_end_time = models.TimeField(
        db_column="policy_off_end_time",
        null=True,
        blank=True,
        help_text="The end time when policy rules should NOT be enforced",
    )
    _policy_off_weekend = models.BooleanField(
        db_column="policy_off_weekend",
        default=False,
        help_text="Whether or not policy rules should be enforced on weekends",
    )
    _operation_mode = models.IntegerField(
        choices=OperationMode.Choices,
        default=OperationMode.REGULAR,
        help_text="The operation mode of the tool, which determines if reservations and wait list are allowed.",
    )

    class Meta:
        ordering = ["name"]

    @property
    def category(self):
        return self.parent_tool.category if self.is_child_tool() else self._category

    @category.setter
    def category(self, value):
        self.raise_setter_error_if_child_tool("category")
        self._category = value

    @property
    def qualifications_never_expire(self):
        return (
            self.parent_tool.qualifications_never_expire if self.is_child_tool() else self._qualifications_never_expire
        )

    @qualifications_never_expire.setter
    def qualifications_never_expire(self, value):
        self.raise_setter_error_if_child_tool("qualifications_never_expire")
        self._qualifications_never_expire = value

    @property
    def description(self):
        return self.parent_tool.description if self.is_child_tool() else self._description

    @description.setter
    def description(self, value):
        self.raise_setter_error_if_child_tool("description")
        self._description = value

    @property
    def serial(self):
        return self.parent_tool.serial if self.is_child_tool() else self._serial

    @serial.setter
    def serial(self, value):
        self.raise_setter_error_if_child_tool("serial")
        self._serial = value

    @property
    def image(self):
        return self.parent_tool.image if self.is_child_tool() else self._image

    @image.setter
    def image(self, value):
        self.raise_setter_error_if_child_tool("image")
        self._image = value

    @property
    def operational(self):
        return self.parent_tool.operational if self.is_child_tool() else self._operational

    @operational.setter
    def operational(self, value):
        self.raise_setter_error_if_child_tool("operational")
        self._operational = value

    @property
    def primary_owner(self) -> User:
        return self.parent_tool.primary_owner if self.is_child_tool() else self._primary_owner

    @primary_owner.setter
    def primary_owner(self, value):
        self.raise_setter_error_if_child_tool("primary_owner")
        self._primary_owner = value

    @property
    def backup_owners(self) -> QuerySetType[User]:
        return self.parent_tool.backup_owners if self.is_child_tool() else self._backup_owners

    @backup_owners.setter
    def backup_owners(self, value):
        self.raise_setter_error_if_child_tool("backup_owners")
        self._backup_owners = value

    @property
    def superusers(self) -> QuerySetType[User]:
        return self.parent_tool.superusers if self.is_child_tool() else self._superusers

    @superusers.setter
    def superusers(self, value):
        self.raise_setter_error_if_child_tool("superusers")
        self._superusers = value

    @property
    def adjustment_request_reviewers(self) -> QuerySetType[User]:
        return (
            self.parent_tool.adjustment_request_reviewers
            if self.is_child_tool()
            else self._adjustment_request_reviewers
        )

    @adjustment_request_reviewers.setter
    def adjustment_request_reviewers(self, value):
        self.raise_setter_error_if_child_tool("_adjustment_request_reviewers")
        self._adjustment_request_reviewers = value

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
    def ask_to_leave_area_when_done_using(self):
        return (
            self.parent_tool.ask_to_leave_area_when_done_using
            if self.is_child_tool()
            else self._ask_to_leave_area_when_done_using
        )

    @ask_to_leave_area_when_done_using.setter
    def ask_to_leave_area_when_done_using(self, value):
        self.raise_setter_error_if_child_tool("ask_to_leave_area_when_done_using")
        self.ask_to_leave_area_when_done_using = value

    @property
    def grant_physical_access_level_upon_qualification(self):
        return (
            self.parent_tool.grant_physical_access_level_upon_qualification
            if self.is_child_tool()
            else self._grant_physical_access_level_upon_qualification
        )

    @grant_physical_access_level_upon_qualification.setter
    def grant_physical_access_level_upon_qualification(self, value):
        self.raise_setter_error_if_child_tool("grant_physical_access_level_upon_qualification")
        self._grant_physical_access_level_upon_qualification = value

    @property
    def grant_badge_reader_access_upon_qualification(self):
        return (
            self.parent_tool.grant_badge_reader_access_upon_qualification
            if self.is_child_tool()
            else self._grant_badge_reader_access_upon_qualification
        )

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
        return (
            self.parent_tool.maximum_reservations_per_day
            if self.is_child_tool()
            else self._maximum_reservations_per_day
        )

    @maximum_reservations_per_day.setter
    def maximum_reservations_per_day(self, value):
        self.raise_setter_error_if_child_tool("maximum_reservations_per_day")
        self._maximum_reservations_per_day = value

    @property
    def minimum_time_between_reservations(self):
        return (
            self.parent_tool.minimum_time_between_reservations
            if self.is_child_tool()
            else self._minimum_time_between_reservations
        )

    @minimum_time_between_reservations.setter
    def minimum_time_between_reservations(self, value):
        self.raise_setter_error_if_child_tool("minimum_time_between_reservations")
        self._minimum_time_between_reservations = value

    @property
    def maximum_future_reservation_time(self):
        return (
            self.parent_tool.maximum_future_reservation_time
            if self.is_child_tool()
            else self._maximum_future_reservation_time
        )

    @maximum_future_reservation_time.setter
    def maximum_future_reservation_time(self, value):
        self.raise_setter_error_if_child_tool("maximum_future_reservation_time")
        self._maximum_future_reservation_time = value

    @property
    def missed_reservation_threshold(self):
        return (
            self.parent_tool.missed_reservation_threshold
            if self.is_child_tool()
            else self._missed_reservation_threshold
        )

    @missed_reservation_threshold.setter
    def missed_reservation_threshold(self, value):
        self.raise_setter_error_if_child_tool("missed_reservation_threshold")
        self._missed_reservation_threshold = value

    @property
    def max_delayed_logoff(self):
        return self.parent_tool.max_delayed_logoff if self.is_child_tool() else self._max_delayed_logoff

    @max_delayed_logoff.setter
    def max_delayed_logoff(self, value):
        self.raise_setter_error_if_child_tool("max_delayed_logoff")
        self._max_delayed_logoff = value

    @property
    def pre_usage_questions(self):
        return self.parent_tool.pre_usage_questions if self.is_child_tool() else self._pre_usage_questions

    @pre_usage_questions.setter
    def pre_usage_questions(self, value):
        self.raise_setter_error_if_child_tool("pre_usage_questions")
        self._pre_usage_questions = value

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

    @property
    def tool_calendar_color(self):
        return self.parent_tool.tool_calendar_color if self.is_child_tool() else self._tool_calendar_color

    @tool_calendar_color.setter
    def tool_calendar_color(self, value):
        self.raise_setter_error_if_child_tool("tool_calendar_color")
        self._tool_calendar_color = value

    @property
    def operation_mode(self):
        return self.parent_tool.operation_mode if self.is_child_tool() else self._operation_mode

    @operation_mode.setter
    def operation_mode(self, value):
        self.raise_setter_error_if_child_tool("operation_mode")
        self._operation_mode = value

    def allow_wait_list(self):
        return self.operation_mode in [self.OperationMode.WAIT_LIST, self.OperationMode.HYBRID]

    def allow_reservation(self):
        return self.operation_mode in [self.OperationMode.REGULAR, self.OperationMode.HYBRID]

    def current_wait_list(self):
        return ToolWaitList.objects.filter(tool=self, expired=False, deleted=False).order_by("date_entered")

    def top_wait_list_entry(self):
        return self.current_wait_list().first()

    def name_or_child_in_use_name(self, parent_ids=None) -> str:
        """This method returns the tool name unless one of its children is in use."""
        """ When used in loops, provide the parent_ids list to avoid unnecessary db calls """
        if self.is_parent_tool(parent_ids) and self.in_use():
            return self.get_current_usage_event().tool.name
        return self.name

    def is_child_tool(self):
        return self.parent_tool is not None

    def is_parent_tool(self, parent_ids=None):
        if not parent_ids:
            parent_ids = list(Tool.objects.filter(parent_tool__isnull=False).values_list("parent_tool_id", flat=True))
        return self.id in parent_ids

    def tool_or_parent_id(self):
        """This method returns the tool id or the parent tool id if tool is a child"""
        if self.is_child_tool():
            return self.parent_tool.id
        else:
            return self.id

    def get_family_tool_ids(self):
        """this method returns a list of children tool ids, parent and self id"""
        tool_ids = list(self.tool_children_set.values_list("id", flat=True))
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

        return reverse("tool_control", args=[self.tool_or_parent_id()])

    def ready_to_use(self):
        return (
            self.operational
            and not self.required_resource_is_unavailable()
            and not self.delayed_logoff_in_progress()
            and not self.scheduled_outage_in_progress()
        )

    def name_display(self):
        return f"{self.name} ({self.parent_tool.name})" if self.is_child_tool() else f"{self.name}"

    name_display.admin_order_field = "name"
    name_display.short_description = "Name"

    def operational_display(self):
        return self.operational

    operational_display.admin_order_field = "_operational"
    operational_display.boolean = True
    operational_display.short_description = "Operational"

    def problematic(self):
        return (
            self.parent_tool.task_set.filter(resolved=False, cancelled=False).exists()
            if self.is_child_tool()
            else self.task_set.filter(resolved=False, cancelled=False).exists()
        )

    problematic.admin_order_field = "task"
    problematic.boolean = True

    def problems(self):
        return (
            self.parent_tool.task_set.filter(resolved=False, cancelled=False)
            if self.is_child_tool()
            else self.task_set.filter(resolved=False, cancelled=False)
        )

    def comments(self):
        unexpired = Q(expiration_date__isnull=True) | Q(expiration_date__gt=timezone.now())
        return (
            self.parent_tool.comment_set.filter(visible=True, staff_only=False).filter(unexpired)
            if self.is_child_tool()
            else self.comment_set.filter(visible=True, staff_only=False).filter(unexpired)
        )

    def staff_only_comments(self):
        unexpired = Q(expiration_date__isnull=True) | Q(expiration_date__gt=timezone.now())
        return (
            self.parent_tool.comment_set.filter(visible=True, staff_only=True).filter(unexpired)
            if self.is_child_tool()
            else self.comment_set.filter(visible=True, staff_only=True).filter(unexpired)
        )

    def required_resource_is_unavailable(self) -> bool:
        return (
            self.parent_tool.required_resource_set.filter(available=False).exists()
            if self.is_child_tool()
            else self.required_resource_set.filter(available=False).exists()
        )

    def nonrequired_resource_is_unavailable(self) -> bool:
        return (
            self.parent_tool.nonrequired_resource_set.filter(available=False).exists()
            if self.is_child_tool()
            else self.nonrequired_resource_set.filter(available=False).exists()
        )

    def all_resources_available(self):
        required_resources_available = not self.unavailable_required_resources().exists()
        nonrequired_resources_available = not self.unavailable_nonrequired_resources().exists()
        if required_resources_available and nonrequired_resources_available:
            return True
        return False

    def unavailable_required_resources(self):
        return (
            self.parent_tool.required_resource_set.filter(available=False)
            if self.is_child_tool()
            else self.required_resource_set.filter(available=False)
        )

    def unavailable_nonrequired_resources(self):
        return (
            self.parent_tool.nonrequired_resource_set.filter(available=False)
            if self.is_child_tool()
            else self.nonrequired_resource_set.filter(available=False)
        )

    def in_use(self):
        result = UsageEvent.objects.filter(tool_id__in=self.get_family_tool_ids(), end=None).exists()
        return result

    def delayed_logoff_in_progress(self):
        result = UsageEvent.objects.filter(tool_id__in=self.get_family_tool_ids(), end__gt=timezone.now()).exists()
        return result

    def get_delayed_logoff_usage_event(self):
        try:
            # TODO: find a better way in case we have future events set up (although it shouldn't happen)
            return UsageEvent.objects.get(tool_id__in=self.get_family_tool_ids(), end__gt=timezone.now())
        except UsageEvent.DoesNotExist:
            return None

    def scheduled_outages(self):
        """Returns a QuerySet of scheduled outages that are in progress for this tool. This includes tool outages, and resources outages (when the tool fully depends on the resource)."""
        return ScheduledOutage.objects.filter(
            Q(tool=self.tool_or_parent_id()) | Q(resource__fully_dependent_tools__in=[self.tool_or_parent_id()]),
            start__lte=timezone.now(),
            end__gt=timezone.now(),
        )

    def scheduled_partial_outages(self):
        """Returns a QuerySet of scheduled outages that are in progress for this tool. This includes resources outages when the tool partially depends on the resource."""
        return ScheduledOutage.objects.filter(
            resource__partially_dependent_tools__in=[self.tool_or_parent_id()],
            start__lte=timezone.now(),
            end__gt=timezone.now(),
        )

    def scheduled_outage_in_progress(self) -> bool:
        """Returns true if a tool or resource outage is currently in effect for this tool. Otherwise, returns false."""
        return ScheduledOutage.objects.filter(
            Q(tool=self.tool_or_parent_id()) | Q(resource__fully_dependent_tools__in=[self.tool_or_parent_id()]),
            start__lte=timezone.now(),
            end__gt=timezone.now(),
        ).exists()

    def enabled_configurations(self):
        return self.configuration_set.filter(enabled=True)

    def is_configurable(self):
        return (
            self.parent_tool.enabled_configurations().exists()
            if self.is_child_tool()
            else self.enabled_configurations().exists()
        )

    is_configurable.admin_order_field = "configuration"
    is_configurable.boolean = True
    is_configurable.short_description = "Configurable"

    def get_configuration_information(self, user, start):
        configurations = self.current_ordered_configurations()
        notice_limit = 0
        able_to_self_configure = True
        for config in configurations:
            notice_limit = max(notice_limit, config.advance_notice_limit)
            # If an item is already excluded from the configuration agenda or the user is not a qualified maintainer, then tool self-configuration is not possible.
            if config.exclude_from_configuration_agenda or not config.user_is_maintainer(user):
                able_to_self_configure = False
        results = {
            "configurations": configurations,
            "notice_limit": notice_limit,
            "able_to_self_configure": able_to_self_configure,
            "additional_information_maximum_length": ADDITIONAL_INFORMATION_MAXIMUM_LENGTH,
        }
        if start:
            results["sufficient_notice"] = start - timedelta(hours=notice_limit) >= timezone.now()
        return results

    def configuration_widget(self, user, render_as_form=None, filter_for_agenda=False):
        configurations = self.current_ordered_configurations()
        if filter_for_agenda:
            configurations = configurations.exclude(exclude_from_configuration_agenda=True)
        config_input = {
            "configurations": configurations,
            "user": user,
            "render_as_form": render_as_form,
        }
        configurations_editor = ConfigurationEditor()
        return configurations_editor.render(None, config_input)

    def current_ordered_configurations(self):
        return (
            self.parent_tool.enabled_configurations().all().order_by("display_order")
            if self.is_child_tool()
            else self.enabled_configurations().all().order_by("display_order")
        )

    def determine_insufficient_notice(self, start):
        """Determines if a reservation is created that does not give
        the staff sufficient advance notice to configure a tool."""
        for config in self.enabled_configurations().all():
            advance_notice = start - timezone.now()
            if advance_notice < timedelta(hours=config.advance_notice_limit):
                return True
        return False

    def get_current_usage_event(self) -> Optional[UsageEvent]:
        """Gets the usage event for the current user of this tool."""
        try:
            return UsageEvent.objects.get(end=None, tool_id__in=self.get_family_tool_ids())
        except UsageEvent.DoesNotExist:
            return None

    def requires_area_reservation(self):
        return self.requires_area_access and self.requires_area_access.requires_reservation

    def active_counters(self):
        return self.toolusagecounter_set.filter(is_active=True)

    def get_tool_info_html(self):
        content = escape(loader.render_to_string("snippets/tool_info.html", {"tool": self}))
        return f'<a href="javascript:;" data-title="{content}" data-tooltip-id="tooltip-tool-{self.id}" data-placement="bottom" class="tool-info-tooltip info-tooltip-container"><span class="glyphicon glyphicon-send small-icon"></span>{self.name_or_child_in_use_name()}</a>'

    def clean(self):
        errors = {}
        if self.parent_tool_id:
            if self.parent_tool_id == self.id:
                errors["parent_tool"] = "You cannot select the parent to be the tool itself."
        else:
            from NEMO.views.customization import ToolCustomization
            from NEMO.widgets.dynamic_form import validate_dynamic_form_model

            if not self._category:
                errors["_category"] = "This field is required."
            if not self._location and ToolCustomization.get_bool("tool_location_required"):
                errors["_location"] = "This field is required."
            if not self._phone_number and ToolCustomization.get_bool("tool_phone_number_required"):
                errors["_phone_number"] = "This field is required."
            if not self._primary_owner_id:
                errors["_primary_owner"] = "This field is required."

            # Validate _pre_usage_questions JSON format
            if self._pre_usage_questions:
                dynamic_form_errors = validate_dynamic_form_model(
                    self._pre_usage_questions, "tool_usage_group_question", self.id
                )
                if dynamic_form_errors:
                    errors["_pre_usage_questions"] = dynamic_form_errors
            # Validate _post_usage_questions JSON format
            if self._post_usage_questions:
                dynamic_form_errors = validate_dynamic_form_model(
                    self._post_usage_questions, "tool_usage_group_question", self.id
                )
                if dynamic_form_errors:
                    errors["_post_usage_questions"] = dynamic_form_errors

            if self._policy_off_between_times and (not self._policy_off_start_time or not self._policy_off_end_time):
                if not self._policy_off_start_time:
                    errors["_policy_off_start_time"] = "Start time must be specified"
                if not self._policy_off_end_time:
                    errors["_policy_off_end_time"] = "End time must be specified"
        if errors:
            raise ValidationError(errors)

    def save(self, force_insert=False, force_update=False, using=None, update_fields=None):
        if self.parent_tool_id:
            # in case of alternate tool, recreate a new tool with only parent_tool and name (never visible)
            fresh_tool = Tool(id=self.id, parent_tool=self.parent_tool, name=self.name, visible=False)
            self.__dict__.update(fresh_tool.__dict__)
        super().save(force_insert, force_update, using, update_fields)


class ToolWaitList(BaseModel):
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        help_text="The user in the wait list.",
    )
    tool = models.ForeignKey(Tool, on_delete=models.CASCADE, help_text="The target tool for the wait list entry.")
    date_entered = models.DateTimeField(auto_now_add=True, help_text="The date/time the user entered the wait list.")
    date_exited = models.DateTimeField(null=True, blank=True, help_text="The date/time the user exited the wait list.")
    last_turn_available_at = models.DateTimeField(
        null=True, blank=True, help_text="The last date/time the user's turn became available."
    )
    expired = models.BooleanField(default=False, help_text="Whether the user's spot in the wait list has expired.")
    deleted = models.BooleanField(default=False, help_text="Whether the wait list entry has been deleted.")


class ToolDocuments(BaseDocumentModel):
    tool = models.ForeignKey(Tool, on_delete=models.CASCADE)

    def get_filename_upload(self, filename):
        from django.template.defaultfilters import slugify

        tool_name = slugify(self.tool.name)
        return f"tool_documents/{tool_name}/{filename}"

    class Meta(BaseDocumentModel.Meta):
        verbose_name_plural = "Tool documents"


class ToolQualificationGroup(SerializationByNameModel):
    name = models.CharField(max_length=CHAR_FIELD_MEDIUM_LENGTH, unique=True, help_text="The name of this tool group")
    tools = models.ManyToManyField(Tool, blank=False)

    def __str__(self):
        return self.name


class Qualification(BaseModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    tool = models.ForeignKey(Tool, on_delete=models.CASCADE)
    qualified_on = models.DateField(default=datetime.date.today)

    class Meta:
        # For db consistency and compatibility with previous queries
        db_table = "NEMO_user_qualifications"


class Configuration(BaseModel, ConfigurationMixin):
    name = models.CharField(
        max_length=CHAR_FIELD_MEDIUM_LENGTH,
        help_text="The name of this overall configuration. This text is displayed as a label on the tool control page.",
    )
    tool = models.ForeignKey(
        Tool, help_text="The tool that this configuration option applies to.", on_delete=models.CASCADE
    )
    configurable_item_name = models.CharField(
        blank=True,
        null=True,
        max_length=CHAR_FIELD_MEDIUM_LENGTH,
        help_text="The name of the tool part being configured. This text is displayed as a label on the tool control page. Leave this field blank if there is only one configuration slot.",
    )
    advance_notice_limit = models.PositiveIntegerField(
        help_text="Configuration changes must be made this many hours in advance."
    )
    display_order = models.PositiveIntegerField(
        help_text="The order in which this configuration will be displayed beside others when making a reservation and controlling a tool. Can be any positive integer including 0. Lower values are displayed first."
    )
    prompt = models.TextField(
        blank=True, null=True, help_text="The textual description the user will see when making a configuration choice."
    )
    current_settings = models.TextField(
        blank=True,
        null=True,
        help_text="The current configuration settings for a tool. Multiple values are separated by commas.",
    )
    available_settings = models.TextField(
        blank=True,
        null=True,
        help_text="The available choices to select for this configuration option. Multiple values are separated by commas.",
    )
    calendar_colors = models.TextField(
        blank=True,
        null=True,
        help_text="Comma separated list of html colors for each available setting. E.g. #ffffff, #eeeeee",
        validators=[color_hex_list_validator],
    )
    absence_string = models.CharField(
        max_length=CHAR_FIELD_SMALL_LENGTH,
        blank=True,
        null=True,
        help_text="The text that appears to indicate absence of a choice.",
    )
    maintainers = models.ManyToManyField(
        User, blank=True, help_text="Select the users that are allowed to change this configuration."
    )
    qualified_users_are_maintainers = models.BooleanField(
        default=False,
        help_text="Any user that is qualified to use the tool that this configuration applies to may also change this configuration. Checking this box implicitly adds qualified users to the maintainers list.",
    )
    exclude_from_configuration_agenda = models.BooleanField(
        default=False,
        help_text="Reservations containing this configuration will be excluded from the Configuration Agenda page.",
    )
    enabled = models.BooleanField(
        default=True, help_text="Only active configurations will show up for the selected tool"
    )

    def get_current_setting(self, slot):
        if slot < 0:
            raise IndexError(
                "Slot index of "
                + str(slot)
                + ' is out of bounds for configuration "'
                + self.name
                + '" (id = '
                + str(self.id)
                + ")."
            )
        return self.current_settings_as_list()[slot]

    def replace_current_setting(self, slot, choice):
        slot = int(slot)
        current_settings = self.current_settings_as_list()
        current_settings[slot] = self.get_available_setting(choice)
        self.current_settings = ", ".join(current_settings)

    def range_of_configurable_items(self):
        return range(0, len(self.current_settings.split(",")))

    def get_color(self, setting):
        index = (
            self.available_settings_as_list().index(setting) if setting in self.available_settings_as_list() else None
        )
        if index is not None:
            color_list = self.calendar_colors_as_list()
            return color_list[index] if color_list and len(color_list) > index else None

    def user_is_maintainer(self, user):
        if user in self.maintainers.all() or user.is_staff:
            return True
        if self.qualified_users_are_maintainers and (user in self.tool.user_set.all() or user.is_staff):
            return True
        return False

    class Meta:
        ordering = ["tool", "name"]

    def __str__(self):
        return str(self.tool.name) + ": " + str(self.name)


class ConfigurationOption(BaseModel, ConfigurationMixin):
    name = models.CharField(max_length=CHAR_FIELD_MEDIUM_LENGTH)
    configuration = models.ForeignKey(
        Configuration,
        null=True,
        blank=True,
        help_text="The configuration this option applies to",
        on_delete=models.SET_NULL,
    )
    reservation = models.ForeignKey(
        "Reservation",
        help_text="The reservation this option is set on",
        on_delete=models.CASCADE,
        related_name="configurationoption_set",
    )
    current_setting = models.CharField(
        null=True,
        blank=True,
        max_length=CHAR_FIELD_MEDIUM_LENGTH,
        help_text="The current value for this configuration option",
    )
    available_settings = models.TextField(
        blank=True,
        null=True,
        help_text="The available choices to select for this configuration option. Multiple values are separated by commas.",
    )
    calendar_colors = models.TextField(
        blank=True,
        null=True,
        help_text="Comma separated list of html colors for each available setting. E.g. #ffffff, #eeeeee",
        validators=[color_hex_list_validator],
    )
    absence_string = models.CharField(
        max_length=CHAR_FIELD_SMALL_LENGTH,
        blank=True,
        null=True,
        help_text="The text that appears to indicate absence of a choice.",
    )

    def get_color(self):
        # if the underlying configuration has not changed (same available settings), use color from config
        same_config = self.configuration and self.configuration.available_settings == self.available_settings
        if same_config:
            return self.configuration.get_color(self.current_setting)
        index = (
            self.available_settings_as_list().index(self.current_setting)
            if self.current_setting in self.available_settings_as_list()
            else None
        )
        if index is not None:
            color_list = self.calendar_colors_as_list()
            return color_list[index] if color_list and len(color_list) > index else None

    def __str__(self):
        selected = f", current value: {self.current_setting}" if self.current_setting else ""
        return f"{self.name}, options: {self.available_settings_as_list()}{selected}"

    class Meta:
        ordering = ["configuration__display_order"]


class TrainingSession(BaseModel, BillableItemMixin):
    class Type(object):
        INDIVIDUAL = 0
        GROUP = 1
        Choices = ((INDIVIDUAL, "Individual"), (GROUP, "Group"))

    trainer = models.ForeignKey(User, related_name="teacher_set", on_delete=models.CASCADE)
    trainee = models.ForeignKey(User, related_name="student_set", on_delete=models.CASCADE)
    tool = models.ForeignKey(Tool, on_delete=models.CASCADE)
    project = models.ForeignKey("Project", on_delete=models.CASCADE)
    duration = models.PositiveIntegerField(help_text="The duration of the training session in minutes.")
    type = models.IntegerField(choices=Type.Choices)
    date = models.DateTimeField(default=timezone.now)
    qualified = models.BooleanField(
        default=False, help_text="Indicates that after this training session the user was qualified to use the tool."
    )
    validated = models.BooleanField(default=False)
    validated_by = models.ForeignKey(
        User, null=True, blank=True, related_name="training_validated_set", on_delete=models.CASCADE
    )
    waived = models.BooleanField(default=False)
    waived_on = models.DateTimeField(null=True, blank=True)
    waived_by = models.ForeignKey(
        User, null=True, blank=True, related_name="training_waived_set", on_delete=models.CASCADE
    )

    def clean(self):
        errors = validate_waive_information(self)
        if errors:
            raise ValidationError(errors)

    class Meta:
        ordering = ["-date"]

    def __str__(self):
        return str(self.id)


class StaffCharge(BaseModel, CalendarDisplayMixin, BillableItemMixin):
    staff_member = models.ForeignKey(User, related_name="staff_charge_actor", on_delete=models.CASCADE)
    customer = models.ForeignKey(User, related_name="staff_charge_customer", on_delete=models.CASCADE)
    project = models.ForeignKey("Project", on_delete=models.CASCADE)
    start = models.DateTimeField(default=timezone.now)
    end = models.DateTimeField(null=True, blank=True)
    note = models.TextField(null=True, blank=True)
    validated = models.BooleanField(default=False)
    validated_by = models.ForeignKey(
        User, null=True, blank=True, related_name="staff_charge_validated_set", on_delete=models.CASCADE
    )
    waived = models.BooleanField(default=False)
    waived_on = models.DateTimeField(null=True, blank=True)
    waived_by = models.ForeignKey(
        User, null=True, blank=True, related_name="staff_charge_waived_set", on_delete=models.CASCADE
    )

    def clean(self):
        errors = validate_waive_information(self)
        if errors:
            raise ValidationError(errors)

    class Meta:
        ordering = ["-start"]

    def __str__(self):
        return f"Staff charge #{self.id}"


class Area(MPTTModel):
    name = models.CharField(
        max_length=CHAR_FIELD_MEDIUM_LENGTH,
        help_text="What is the name of this area? The name will be displayed on the tablet login and logout pages.",
    )
    parent_area = TreeForeignKey(
        "self",
        related_name="area_children_set",
        null=True,
        blank=True,
        help_text="Select a parent area, (building, floor etc.)",
        on_delete=models.CASCADE,
    )
    category = models.CharField(
        db_column="category",
        null=True,
        blank=True,
        max_length=CHAR_FIELD_LARGE_LENGTH,
        help_text='Create sub-categories using slashes. For example "Category 1/Sub-category 1".',
    )
    abuse_email: List[str] = fields.MultiEmailField(
        null=True,
        blank=True,
        help_text="An email will be sent to this address when users overstay in the area or in children areas (logged in with expired reservation). A comma-separated list can be used.",
    )
    reservation_email: List[str] = fields.MultiEmailField(
        null=True,
        blank=True,
        help_text="An email will be sent to this address when users create or cancel reservations in the area or in children areas. A comma-separated list can be used.",
    )

    # Area permissions
    adjustment_request_reviewers = models.ManyToManyField(
        User,
        blank=True,
        related_name="adjustment_request_reviewer_on_areas",
        help_text="Users who can approve/deny adjustment requests for this area. Defaults to facility managers if left blank.",
    )
    access_request_reviewers = models.ManyToManyField(
        User,
        blank=True,
        related_name="access_request_reviewer_on_areas",
        help_text="Users who can approve/deny access requests for this area. Defaults to facility managers if left blank.",
    )

    # Additional information
    area_calendar_color = models.CharField(
        max_length=9,
        default="#88B7CD",
        help_text="Color for tool reservations in calendar overviews",
        validators=[color_hex_validator],
    )

    # Area access
    requires_reservation = models.BooleanField(
        default=False, help_text="Check this box to require a reservation for this area before a user can login."
    )
    logout_grace_period = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Number of minutes users have to logout of this area after their reservation expired before being flagged and abuse email is sent.",
    )
    auto_logout_time = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Number of minutes after which users will be automatically logged out of this area.",
    )
    buddy_system_allowed = models.BooleanField(
        default=False, help_text="Check this box if the buddy system is allowed in this area."
    )

    # Capacity
    maximum_capacity = models.PositiveIntegerField(
        help_text="The maximum number of people allowed in this area at any given time. Set to 0 for unlimited.",
        default=0,
    )
    count_staff_in_occupancy = models.BooleanField(
        default=True, help_text="Indicates that staff users will count towards maximum capacity."
    )
    count_service_personnel_in_occupancy = models.BooleanField(
        default=True, help_text="Indicates that service personnel will count towards maximum capacity."
    )
    reservation_warning = models.PositiveIntegerField(
        blank=True,
        null=True,
        help_text="The number of simultaneous users (with at least one reservation in this area) allowed before a warning is displayed when creating a reservation.",
    )

    # Policy rules
    reservation_horizon = models.PositiveIntegerField(
        db_column="reservation_horizon",
        default=14,
        null=True,
        blank=True,
        help_text="Users may create reservations this many days in advance. Leave this field blank to indicate that no reservation horizon exists for this area.",
    )
    missed_reservation_threshold = models.PositiveIntegerField(
        db_column="missed_reservation_threshold",
        null=True,
        blank=True,
        help_text='The amount of time (in minutes) that a area reservation may go unused before it is automatically marked as "missed" and hidden from the calendar. Usage can be from any user, regardless of who the reservation was originally created for. The cancellation process is triggered by a timed job on the web server.',
    )
    minimum_usage_block_time = models.PositiveIntegerField(
        db_column="minimum_usage_block_time",
        null=True,
        blank=True,
        help_text="The minimum amount of time (in minutes) that a user must reserve this area for a single reservation. Leave this field blank to indicate that no minimum usage block time exists for this area.",
    )
    maximum_usage_block_time = models.PositiveIntegerField(
        db_column="maximum_usage_block_time",
        null=True,
        blank=True,
        help_text="The maximum amount of time (in minutes) that a user may reserve this area for a single reservation. Leave this field blank to indicate that no maximum usage block time exists for this area.",
    )
    maximum_reservations_per_day = models.PositiveIntegerField(
        db_column="maximum_reservations_per_day",
        null=True,
        blank=True,
        help_text="The maximum number of reservations a user may make per day for this area.",
    )
    minimum_time_between_reservations = models.PositiveIntegerField(
        db_column="minimum_time_between_reservations",
        null=True,
        blank=True,
        help_text="The minimum amount of time (in minutes) that the same user must have between any two reservations for this area.",
    )
    maximum_future_reservation_time = models.PositiveIntegerField(
        db_column="maximum_future_reservation_time",
        null=True,
        blank=True,
        help_text="The maximum amount of time (in minutes) that a user may reserve from the current time onwards.",
    )
    policy_off_between_times = models.BooleanField(
        db_column="policy_off_between_times",
        default=False,
        help_text="Check this box to disable policy rules every day between the given times",
    )
    policy_off_start_time = models.TimeField(
        db_column="policy_off_start_time",
        null=True,
        blank=True,
        help_text="The start time when policy rules should NOT be enforced",
    )
    policy_off_end_time = models.TimeField(
        db_column="policy_off_end_time",
        null=True,
        blank=True,
        help_text="The end time when policy rules should NOT be enforced",
    )
    policy_off_weekend = models.BooleanField(
        db_column="policy_off_weekend",
        default=False,
        help_text="Whether or not policy rules should be enforced on weekends",
    )

    class MPTTMeta:
        parent_attr = "parent_area"

    class Meta:
        indexes = [
            models.Index(fields=["name"]),
        ]

    def __str__(self):
        return self.name

    def tree_category(self):
        tree_category = "/".join([ancestor.name for ancestor in self.get_ancestors().only("name")])
        if self.category:
            tree_category += "/" + self.category if tree_category else self.category
        return tree_category

    def is_now_a_parent(self):
        """This method is called when this area is a parent of another area"""
        if self.is_leaf_node():
            # Only need to clean this area if it doesn't yet have children
            self.requires_reservation = False
            self.reservation_horizon = None
            self.missed_reservation_threshold = None
            self.minimum_usage_block_time = None
            self.maximum_usage_block_time = None
            self.maximum_reservations_per_day = None
            self.minimum_time_between_reservations = None
            self.maximum_future_reservation_time = None
            self.policy_off_between_times = False
            self.policy_off_start_time = None
            self.policy_off_end_time = None
            self.policy_off_weekend = False
            self.save()

    def warning_capacity(self):
        return self.reservation_warning if self.reservation_warning is not None else sys.maxsize

    def danger_capacity(self):
        return self.maximum_capacity

    def occupancy_count(self):
        """Returns the occupancy used to determine if the area is at capacity"""
        result = self.occupancy()
        if not self.count_staff_in_occupancy:
            result = result - self.occupancy_staff()
        if not self.count_service_personnel_in_occupancy:
            result = result - self.occupancy_service_personnel()
        return result

    def occupancy_staff(self):
        return AreaAccessRecord.objects.filter(
            area__in=self.get_descendants(include_self=True), end=None, staff_charge=None, customer__is_staff=True
        ).count()

    def occupancy_service_personnel(self):
        return AreaAccessRecord.objects.filter(
            area__in=self.get_descendants(include_self=True),
            end=None,
            staff_charge=None,
            customer__is_service_personnel=True,
        ).count()

    def occupancy(self):
        return AreaAccessRecord.objects.filter(
            area__in=self.get_descendants(include_self=True), end=None, staff_charge=None
        ).count()

    def get_physical_access_levels(self):
        """Returns access levels for this area and descendants"""
        return PhysicalAccessLevel.objects.filter(area_id__in=self.get_descendants(include_self=True))

    def required_resource_is_unavailable(self) -> bool:
        required_resource_unavailable = False
        for a in self.get_ancestors(ascending=True, include_self=True):
            if a.required_resources.filter(available=False).exists():
                required_resource_unavailable = True
                break
        return required_resource_unavailable

    def scheduled_outage_in_progress(self) -> bool:
        """Returns true if an area or resource outage is currently in effect for this area (or parent). Otherwise, returns false."""
        return self.scheduled_outage_queryset().filter(start__lte=timezone.now(), end__gt=timezone.now()).exists()

    def scheduled_outage_queryset(self):
        ids = [area.id for area in self.get_ancestors(include_self=True)]
        return ScheduledOutage.objects.filter(Q(area_id__in=ids) | Q(resource__dependent_areas__in=ids))

    def get_current_reservation_for_user(self, user):
        if self.requires_reservation:
            return Reservation.objects.filter(
                missed=False,
                cancelled=False,
                shortened=False,
                user=user,
                area=self,
                start__lte=timezone.now(),
                end__gt=timezone.now(),
            )

    def abuse_email_list(self):
        return [email for area in self.get_ancestors(ascending=True, include_self=True) for email in area.abuse_email]

    def reservation_email_list(self):
        return [
            email for area in self.get_ancestors(ascending=True, include_self=True) for email in area.reservation_email
        ]


class AreaAccessRecord(BaseModel, CalendarDisplayMixin, BillableItemMixin):
    area = TreeForeignKey(Area, on_delete=models.CASCADE)
    customer = models.ForeignKey(User, on_delete=models.CASCADE)
    project = models.ForeignKey("Project", on_delete=models.CASCADE)
    start = models.DateTimeField(default=timezone.now)
    end = models.DateTimeField(null=True, blank=True)
    staff_charge = models.ForeignKey(StaffCharge, blank=True, null=True, on_delete=models.CASCADE)
    validated = models.BooleanField(default=False)
    validated_by = models.ForeignKey(
        User, null=True, blank=True, related_name="area_access_validated_set", on_delete=models.CASCADE
    )
    waived = models.BooleanField(default=False)
    waived_on = models.DateTimeField(null=True, blank=True)
    waived_by = models.ForeignKey(
        User, null=True, blank=True, related_name="area_access_waived_set", on_delete=models.CASCADE
    )

    def clean(self):
        errors = validate_waive_information(self)
        if errors:
            raise ValidationError(errors)

    class Meta:
        indexes = [
            models.Index(fields=["end"]),
        ]

    def __str__(self):
        return str(self.id)


class ConfigurationHistory(BaseModel):
    configuration = models.ForeignKey(Configuration, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    modification_time = models.DateTimeField(default=timezone.now)
    item_name = models.CharField(null=True, blank=False, max_length=CHAR_FIELD_MEDIUM_LENGTH)
    slot = models.PositiveIntegerField()
    setting = models.TextField()

    class Meta:
        ordering = ["-modification_time"]
        verbose_name_plural = "Configuration histories"

    def __str__(self):
        return str(self.id)


class AccountType(BaseCategory):
    pass


class Account(SerializationByNameModel):
    name = models.CharField(max_length=CHAR_FIELD_SMALL_LENGTH, unique=True)
    type = models.ForeignKey(AccountType, null=True, blank=True, on_delete=models.SET_NULL)
    start_date = models.DateField(null=True, blank=True)
    active = models.BooleanField(
        default=True,
        help_text="Users may only charge to an account if it is active. Deactivate the account to block future billable activity (such as tool usage and consumable check-outs) of all the projects that belong to it.",
    )

    class Meta:
        ordering = ["name"]

    def sorted_active_projects(self):
        return self.sorted_projects().filter(active=True)

    def sorted_projects(self):
        return self.project_set.all().order_by("-active", "name")

    def display_with_status(self):
        return f"{'[INACTIVE] ' if not self.active else ''}{self.name}"

    def __str__(self):
        return str(self.name)


class Project(SerializationByNameModel):
    name = models.CharField(max_length=CHAR_FIELD_LARGE_LENGTH, unique=True)
    application_identifier = models.CharField(max_length=CHAR_FIELD_SMALL_LENGTH)
    start_date = models.DateField(null=True, blank=True)
    account = models.ForeignKey(
        Account,
        help_text="All charges for this project will be billed to the selected account.",
        on_delete=models.CASCADE,
    )
    discipline = models.ForeignKey(ProjectDiscipline, null=True, blank=True, on_delete=models.SET_NULL)
    active = models.BooleanField(
        default=True,
        help_text="Users may only charge to a project if it is active. Deactivate the project to block billable activity (such as tool usage and consumable check-outs).",
    )
    only_allow_tools = models.ManyToManyField(
        Tool, blank=True, help_text="Selected tools will be the only ones allowed for this project."
    )
    allow_consumable_withdrawals = models.BooleanField(
        default=True, help_text="Uncheck this box if consumable withdrawals are forbidden under this project"
    )
    allow_staff_charges = models.BooleanField(
        default=True, help_text="Uncheck this box if staff charges are forbidden for this project"
    )

    class Meta:
        ordering = ["name"]

    def display_with_pis(self):
        from NEMO.templatetags.custom_tags_and_filters import project_selection_display

        pis = ", ".join([pi.get_name() for pi in self.manager_set.all()])
        pis = f" (PI{'s' if self.manager_set.count() > 1 else ''}: {pis})" if pis else ""
        return f"{project_selection_display(self)}{pis}"

    def display_with_status(self):
        return f"{'[INACTIVE] ' if not self.active else ''}{self.name}"

    def __str__(self):
        return str(self.name)


class ProjectDocuments(BaseDocumentModel):
    project = models.ForeignKey(Project, related_name="project_documents", on_delete=models.CASCADE)

    def get_filename_upload(self, filename):
        from django.template.defaultfilters import slugify

        project_name = slugify(self.project.name)
        return f"project_documents/{project_name}/{filename}"

    class Meta(BaseDocumentModel.Meta):
        verbose_name_plural = "Project documents"


def pre_delete_entity(sender, instance, using, **kwargs):
    """Remove activity history and membership history when an account, project, tool, or user is deleted."""
    content_type = ContentType.objects.get_for_model(sender)
    ActivityHistory.objects.filter(object_id=instance.id, content_type=content_type).delete()
    MembershipHistory.objects.filter(parent_object_id=instance.id, parent_content_type=content_type).delete()
    MembershipHistory.objects.filter(child_object_id=instance.id, child_content_type=content_type).delete()


# Call the function "pre_delete_entity" every time an account, project, tool, or user is deleted:
pre_delete.connect(pre_delete_entity, sender=Account)
pre_delete.connect(pre_delete_entity, sender=Project)
pre_delete.connect(pre_delete_entity, sender=Tool)
pre_delete.connect(pre_delete_entity, sender=User)


class Reservation(BaseModel, CalendarDisplayMixin, BillableItemMixin):
    user = models.ForeignKey(User, related_name="reservation_user", on_delete=models.CASCADE)
    creator = models.ForeignKey(User, related_name="reservation_creator", on_delete=models.CASCADE)
    creation_time = models.DateTimeField(default=timezone.now)
    tool = models.ForeignKey(Tool, null=True, blank=True, on_delete=models.CASCADE)
    area = TreeForeignKey(Area, null=True, blank=True, on_delete=models.CASCADE)
    project = models.ForeignKey(
        Project,
        null=True,
        blank=True,
        help_text="Indicates the intended project for this reservation. A missed reservation would be billed to this project.",
        on_delete=models.CASCADE,
    )
    start = models.DateTimeField("start")
    end = models.DateTimeField("end")
    short_notice = models.BooleanField(
        default=None,
        help_text="Indicates that the reservation was made after the configuration deadline for a tool. Staff may not have enough time to properly configure the tool before the user is scheduled to use it.",
    )
    cancelled = models.BooleanField(
        default=False, help_text="Indicates that the reservation has been cancelled, moved, or resized."
    )
    cancellation_time = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    missed = models.BooleanField(
        default=False,
        help_text='Indicates that the tool was not enabled by anyone before the tool\'s "missed reservation threshold" passed.',
    )
    shortened = models.BooleanField(
        default=False,
        help_text="Indicates that the user finished using the tool and relinquished the remaining time on their reservation. The reservation will no longer be visible on the calendar and a descendant reservation will be created in place of the existing one.",
    )
    descendant = models.OneToOneField(
        "Reservation",
        related_name="ancestor",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        help_text="Any time a reservation is moved or resized, the old reservation is cancelled and a new reservation with updated information takes its place. This field links the old reservation to the new one, so the history of reservation moves & changes can be easily tracked.",
    )
    additional_information = models.TextField(null=True, blank=True)
    self_configuration = models.BooleanField(
        default=False,
        help_text="When checked, indicates that the user will perform their own tool configuration (instead of requesting that the staff configure it for them).",
    )
    title = models.TextField(
        default="",
        blank=True,
        max_length=CHAR_FIELD_MEDIUM_LENGTH,
        help_text="Shows a custom title for this reservation on the calendar. Leave this field blank to display the reservation's user name as the title (which is the default behaviour).",
    )
    question_data = models.TextField(null=True, blank=True)
    validated = models.BooleanField(default=False)
    validated_by = models.ForeignKey(
        User, null=True, blank=True, related_name="reservation_validated_set", on_delete=models.CASCADE
    )
    waived = models.BooleanField(default=False)
    waived_on = models.DateTimeField(null=True, blank=True)
    waived_by = models.ForeignKey(
        User, null=True, blank=True, related_name="reservation_waived_set", on_delete=models.CASCADE
    )

    @property
    def reservation_item(self) -> Union[Tool, Area]:
        if self.tool:
            return self.tool
        elif self.area:
            return self.area

    @reservation_item.setter
    def reservation_item(self, item):
        if isinstance(item, Tool):
            self.tool = item
        elif isinstance(item, Area):
            self.area = item
        else:
            raise AttributeError(f"This item [{item}] isn't allowed on reservations.")

    @property
    def reservation_item_type(self) -> ReservationItemType:
        if self.tool:
            return ReservationItemType.TOOL
        elif self.area:
            return ReservationItemType.AREA

    @property
    def reservation_item_filter(self):
        return {self.reservation_item_type.value: self.reservation_item}

    def duration(self):
        return self.end - self.start

    def duration_for_policy(self):
        # This method returns the duration that counts for policy checks.
        # i.e. reservation duration minus any time when the policy is off
        item = self.reservation_item
        if item and isinstance(item, (Tool, Area)):
            return get_duration_with_off_schedule(
                self.start,
                self.end,
                item.policy_off_weekend,
                item.policy_off_between_times,
                item.policy_off_start_time,
                item.policy_off_end_time,
            )
        return self.duration()

    def has_not_ended(self):
        return False if self.end < timezone.now() else True

    def has_not_started(self):
        return False if self.start <= timezone.now() else True

    def get_configuration_options_display(self):
        result = ""
        for config_option in self.configurationoption_set.all():
            result += f"{config_option.name}: {config_option.current_setting}\n"
        return result

    def get_configuration_options_colors(self):
        colors = []
        for config_option in self.configurationoption_set.all():
            colors.append(config_option.get_color() or "#5561ec")
        return colors

    def save(self, force_insert=False, force_update=False, using=None, update_fields=None):
        super().save(force_insert, force_update, using, update_fields)
        deferred_related_models = getattr(self, "_deferred_related_models", None)
        if deferred_related_models:
            for deferred_related_model in deferred_related_models:
                deferred_related_model.save()

    def save_and_notify(self):
        self.save()
        from NEMO.views.calendar import (
            send_user_cancelled_reservation_notification,
            send_user_created_reservation_notification,
        )

        if self.cancelled:
            send_user_cancelled_reservation_notification(self)
        else:
            send_user_created_reservation_notification(self)

    def question_data_json(self):
        return loads(self.question_data) if self.question_data else None

    def copy(self, new_start: datetime = None, new_end: datetime = None):
        new_reservation = new_model_copy(self)
        if new_start:
            new_reservation.start = new_start
        if new_end:
            new_reservation.end = new_end
        if new_reservation.tool:
            new_reservation.short_notice = new_reservation.tool.determine_insufficient_notice(new_reservation.start)
        # If we have configuration options, we have to save them later since this copy does not save the reservation
        # In the reservation save method, it will check for the existence of this
        if self.configurationoption_set.exists():
            deferred_related_models = []
            for config_option in self.configurationoption_set.all():
                new_config_option = new_model_copy(config_option)
                new_config_option.reservation = new_reservation
                deferred_related_models.append(new_config_option)
            new_reservation._deferred_related_models = deferred_related_models
        return new_reservation

    def clean(self):
        errors = validate_waive_information(self)
        if errors:
            raise ValidationError(errors)

    class Meta:
        ordering = ["-start"]

    def __str__(self):
        return str(self.id)


class ReservationQuestions(BaseModel):
    name = models.CharField(max_length=CHAR_FIELD_SMALL_LENGTH, help_text="The name of this ")
    questions = models.TextField(
        help_text="Upon making a reservation, the user will be asked these questions. This field will only accept JSON format"
    )
    tool_reservations = models.BooleanField(
        default=True, help_text="Check this box to apply these questions to tool reservations"
    )
    only_for_tools = models.ManyToManyField(
        Tool, blank=True, help_text="Select the tools these questions only apply to. Leave blank for all tools"
    )
    area_reservations = models.BooleanField(
        default=False, help_text="Check this box to apply these questions to area reservations"
    )
    only_for_areas = models.ManyToManyField(
        Area, blank=True, help_text="Select the areas these questions only apply to. Leave blank for all areas"
    )
    only_for_projects = models.ManyToManyField(
        Project, blank=True, help_text="Select the projects these questions only apply to. Leave blank for all projects"
    )

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "Reservation questions"

    def __str__(self):
        return self.name


class UsageEvent(BaseModel, CalendarDisplayMixin, BillableItemMixin):
    user = models.ForeignKey(User, related_name="usage_event_user", on_delete=models.CASCADE)
    operator = models.ForeignKey(User, related_name="usage_event_operator", on_delete=models.CASCADE)
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    tool = models.ForeignKey(
        Tool, related_name="+", on_delete=models.CASCADE
    )  # The related_name='+' disallows reverse lookups. Helper functions of other models should be used instead.
    start = models.DateTimeField(default=timezone.now)
    end = models.DateTimeField(null=True, blank=True)
    validated = models.BooleanField(default=False)
    validated_by = models.ForeignKey(
        User, null=True, blank=True, related_name="usage_event_validated_set", on_delete=models.CASCADE
    )
    remote_work = models.BooleanField(default=False)
    pre_run_data = models.TextField(null=True, blank=True)
    run_data = models.TextField(null=True, blank=True)
    waived = models.BooleanField(default=False)
    waived_on = models.DateTimeField(null=True, blank=True)
    waived_by = models.ForeignKey(
        User, null=True, blank=True, related_name="usage_event_waived_set", on_delete=models.CASCADE
    )

    def clean(self):
        errors = validate_waive_information(self)
        if errors:
            raise ValidationError(errors)

    def duration(self):
        return calculate_duration(self.start, self.end, "In progress")

    class Meta:
        ordering = ["-start"]

    def __str__(self):
        return str(self.id)


class Consumable(BaseModel):
    name = models.CharField(max_length=CHAR_FIELD_SMALL_LENGTH)
    category = models.ForeignKey("ConsumableCategory", blank=True, null=True, on_delete=models.CASCADE)
    quantity = models.IntegerField(help_text="The number of items currently in stock.")
    reusable = models.BooleanField(
        default=False,
        help_text="Check this box if this item is reusable. The quantity of reusable items will not decrease when orders are made (storage bins for example).",
    )
    visible = models.BooleanField(default=True)
    allow_self_checkout = models.BooleanField(
        default=True,
        help_text="Allow users to self checkout this consumable, only applicable when self checkout customization is enabled.",
    )
    self_checkout_only_users = models.ManyToManyField(
        User,
        blank=True,
        help_text="Selected users will be the only ones allowed to self checkout this consumable. Leave blank for all.",
    )
    notes = models.TextField(null=True, blank=True, help_text="Notes about the consumable.")
    reminder_threshold = models.IntegerField(
        null=True,
        blank=True,
        help_text="More of this item should be ordered when the quantity falls below this threshold.",
    )
    reminder_email = models.EmailField(
        null=True,
        blank=True,
        help_text="An email will be sent to this address when the quantity of this item falls below the reminder threshold.",
    )
    reminder_threshold_reached = models.BooleanField(default=False)

    class Meta:
        ordering = ["name"]

    def clean(self):
        if not self.reusable and (not self.reminder_threshold or not self.reminder_email):
            raise ValidationError(
                {
                    "reminder_threshold": "This field is required when the item is not reusable",
                    "reminder_email": "This field is required when the item is not reusable",
                }
            )

    def __str__(self):
        return self.name


# This method is used to check when the quantity of a consumable falls below the threshold
# or when it has been replenished
@receiver(models.signals.pre_save, sender=Consumable)
def check_consumable_quantity_threshold(sender, instance: Consumable, **kwargs):
    try:
        if instance.reminder_threshold:
            if not instance.reminder_threshold_reached and instance.quantity < instance.reminder_threshold:
                # quantity is below threshold. set flag and send email
                instance.reminder_threshold_reached = True
                from NEMO.views.consumables import send_reorder_supply_reminder_email

                send_reorder_supply_reminder_email(instance)
            if instance.reminder_threshold_reached and instance.quantity >= instance.reminder_threshold:
                # it has been replenished. reset flag
                instance.reminder_threshold_reached = False
    except Exception as e:
        models_logger.exception(e)
        pass


class ConsumableCategory(BaseModel):
    name = models.CharField(max_length=CHAR_FIELD_SMALL_LENGTH)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "Consumable categories"

    def __str__(self):
        return self.name


class ConsumableWithdraw(BaseModel, BillableItemMixin):
    customer = models.ForeignKey(
        User,
        related_name="consumable_user",
        help_text="The user who will use the consumable item.",
        on_delete=models.CASCADE,
    )
    merchant = models.ForeignKey(
        User,
        related_name="consumable_merchant",
        help_text="The staff member that performed the withdraw.",
        on_delete=models.CASCADE,
    )
    consumable = models.ForeignKey(Consumable, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField()
    project = models.ForeignKey(
        Project, help_text="The withdraw will be billed to this project.", on_delete=models.CASCADE
    )
    date = models.DateTimeField(
        default=timezone.now, help_text="The date and time when the user withdrew the consumable."
    )
    usage_event = models.ForeignKey(
        UsageEvent,
        null=True,
        blank=True,
        help_text="Whether this withdraw is from tool usage",
        on_delete=models.CASCADE,
    )
    validated = models.BooleanField(default=False)
    validated_by = models.ForeignKey(
        User, null=True, blank=True, related_name="consumable_withdrawal_validated_set", on_delete=models.CASCADE
    )
    waived = models.BooleanField(default=False)
    waived_on = models.DateTimeField(null=True, blank=True)
    waived_by = models.ForeignKey(
        User, null=True, blank=True, related_name="consumable_withdrawal_waived_set", on_delete=models.CASCADE
    )

    class Meta:
        ordering = ["-date"]

    @property
    def tool_usage(self) -> bool:
        return bool(self.usage_event)

    def clean(self):
        errors = {}
        if self.customer_id:
            if not self.customer.is_active:
                errors["customer"] = (
                    "A consumable withdraw was requested for an inactive user. Only active users may withdraw consumables."
                )
            if self.customer.has_access_expired():
                errors["customer"] = f"This user's access expired on {format_datetime(self.customer.access_expiration)}"
        if self.project_id:
            if not self.project.active:
                errors["project"] = (
                    "A consumable may only be billed to an active project. The user's project is inactive."
                )
            if not self.project.account.active:
                errors["project"] = (
                    "A consumable may only be billed to a project that belongs to an active account. The user's account is inactive."
                )
        if self.quantity is not None and self.quantity < 1:
            errors["quantity"] = "Please specify a valid quantity of items to withdraw."
        if self.consumable_id:
            if not self.consumable.reusable and self.quantity > self.consumable.quantity:
                errors[NON_FIELD_ERRORS] = (
                    f'There are not enough "{self.consumable.name}". (The current quantity in stock is {str(self.consumable.quantity)}). Please order more as soon as possible.'
                )
        if self.customer_id and self.consumable_id and self.project_id:
            from NEMO.exceptions import ProjectChargeException
            from NEMO.policy import policy_class as policy

            try:
                policy.check_billing_to_project(self.project, self.customer, self.consumable, self)
            except ProjectChargeException as e:
                errors["project"] = e.msg
        errors.update(validate_waive_information(self))
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return str(self.id)


class RecurringConsumableCharge(BaseModel, RecurrenceMixin):
    name = models.CharField(
        max_length=CHAR_FIELD_MEDIUM_LENGTH, help_text="The name/identifier for this recurring charge."
    )
    customer = models.ForeignKey(
        User,
        null=True,
        blank=True,
        related_name="recurring_charge_customer",
        help_text="The user who will be charged.",
        on_delete=models.CASCADE,
    )
    consumable = models.ForeignKey(Consumable, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(
        default=1, validators=[MinValueValidator(1)], help_text="The number of consumables to charge."
    )
    project = models.ForeignKey(
        Project, null=True, blank=True, help_text="The project to bill.", on_delete=models.CASCADE
    )
    last_charge = models.DateTimeField(
        null=True, blank=True, help_text="The date and time when the user was last charged."
    )
    # Recurring schedule. TODO: think about extracting into its own model if used anywhere else
    rec_start = models.DateField(
        verbose_name="start", null=True, blank=True, help_text="Start date of the recurring charge."
    )
    rec_frequency = models.PositiveIntegerField(
        verbose_name="frequency",
        null=True,
        blank=True,
        choices=RecurrenceFrequency.choices(),
        help_text="The charge frequency.",
    )
    rec_interval = models.PositiveIntegerField(
        verbose_name="interval",
        default=1,
        validators=[MinValueValidator(1)],
        help_text="Recurring interval, i.e. every 5 days.",
    )
    rec_until = models.DateField(
        verbose_name="until", null=True, blank=True, help_text="End date of the recurring charge."
    )
    rec_count = models.PositiveIntegerField(
        verbose_name="count",
        null=True,
        blank=True,
        validators=[MinValueValidator(1)],
        help_text="The number of recurrences to charge for.",
    )
    # Audit
    last_updated = models.DateTimeField(help_text="The time this charge was last modified.")
    last_updated_by = models.ForeignKey(
        "User",
        related_name="recurring_charge_updated",
        help_text="The user who last modified this charge (and will be used as merchant on the charge).",
        on_delete=models.PROTECT,
    )

    class Meta:
        ordering = ["name"]

    def next_charge(self, inc=False) -> datetime:
        return self.next_recurrence(inc)

    def invalid_customer(self):
        from NEMO.views.customization import RecurringChargesCustomization

        skip_customer = RecurringChargesCustomization.get_bool("recurring_charges_skip_customer_validation")
        if self.customer and not skip_customer:
            if not self.customer.is_active:
                return "This user is inactive"
            if self.customer.has_access_expired():
                return (
                    f"The facility access for this user expired on {format_datetime(self.customer.access_expiration)}"
                )

    def invalid_project(self):
        if self.project:
            if not self.project.active:
                return "This project is inactive"
            if not self.project.account.active:
                return "The account for this project is inactive"
            if not self.project.allow_consumable_withdrawals:
                return "This project doesn't allow consumable charges"
        if self.customer and self.project:
            if self.project not in self.customer.active_projects():
                return "The user does not belong to this project"

    def charge(self):
        # Cannot charge twice the same day
        if self.last_charge and as_timezone(self.last_charge).date() == datetime.date.today():
            return
        else:
            from NEMO.views.consumables import make_withdrawal

            self.full_clean()
            make_withdrawal(self.consumable.id, self.quantity, self.project.id, self.last_updated_by, self.customer.id)
            self.last_charge = timezone.now()
            self.save()

    def is_empty(self):
        return not any([self.customer_id, self.project_id])

    def clear(self):
        self.customer = None
        self.project = None
        self.last_charge = None
        self.save()

    def clean(self):
        if not self.is_empty():
            errors = {}
            if not self.customer:
                errors["customer"] = "This field is required."
            if not self.project:
                errors["project"] = "This field is required."
            errors.update(self.clean_recurrence())
            # Validate needed fields are present
            if errors:
                raise ValidationError(errors)
            # Validate if we have everything to charge
            from NEMO.forms import ConsumableWithdrawForm
            from NEMO.views.customization import RecurringChargesCustomization

            skip_customer = RecurringChargesCustomization.get_bool("recurring_charges_skip_customer_validation")
            charge_form = ConsumableWithdrawForm(
                {
                    "customer": self.customer_id,
                    "project": self.project_id,
                    "consumable": self.consumable_id,
                    "quantity": self.quantity,
                }
            )
            if not charge_form.is_valid():
                if not skip_customer or list(charge_form.errors.keys()) != ["customer"]:
                    raise ValidationError(charge_form.errors)

    def save_with_user(self, user: User, *args, **kwargs):
        self.last_updated_by = user
        self.last_updated = timezone.now()
        super().save(*args, **kwargs)

    @transaction.atomic
    def save_and_charge_with_user(self, user: User):
        self.save_with_user(user)
        self.charge()

    def search_display(self):
        display_attributes = [self.name]
        if self.customer:
            display_attributes.append(str(self.customer))
        if self.project:
            display_attributes.append(str(self.project))
        return " - ".join(display_attributes)

    def __str__(self):
        return self.name


class InterlockCard(BaseModel):
    name = models.CharField(max_length=CHAR_FIELD_SMALL_LENGTH, blank=True, null=True)
    server = models.CharField(max_length=CHAR_FIELD_SMALL_LENGTH)
    port = models.PositiveIntegerField()
    number = models.PositiveIntegerField(blank=True, null=True)
    even_port = models.PositiveIntegerField(blank=True, null=True)
    odd_port = models.PositiveIntegerField(blank=True, null=True)
    category = models.ForeignKey("InterlockCardCategory", blank=False, null=False, on_delete=models.CASCADE, default=1)
    username = models.CharField(max_length=CHAR_FIELD_SMALL_LENGTH, blank=True, null=True)
    password = models.CharField(max_length=CHAR_FIELD_SMALL_LENGTH, blank=True, null=True)
    enabled = models.BooleanField(blank=False, null=False, default=True)

    class Meta:
        ordering = ["server", "number"]

    def __str__(self):
        card_name = self.name + ": " if self.name else ""
        return card_name + str(self.server) + (", card " + str(self.number) if self.number else "")


class Interlock(BaseModel):
    class State(object):
        UNKNOWN = -1
        # The numeric command types for the interlock hardware:
        UNLOCKED = 1
        LOCKED = 2
        Choices = (
            (UNKNOWN, "Unknown"),
            (
                UNLOCKED,
                "Unlocked",
            ),  # The 'unlocked' and 'locked' constants match the hardware command types to control the interlocks.
            (LOCKED, "Locked"),
        )

    name = models.CharField(null=True, blank=True, max_length=CHAR_FIELD_MEDIUM_LENGTH)
    card = models.ForeignKey(InterlockCard, on_delete=models.CASCADE)
    channel = models.PositiveIntegerField(blank=True, null=True, verbose_name="Channel/Relay/Coil")
    unit_id = models.PositiveIntegerField(null=True, blank=True, verbose_name="Multiplier/Unit id/Bank")
    state = models.IntegerField(choices=State.Choices, default=State.UNKNOWN)
    most_recent_reply = models.TextField(default="None")
    most_recent_reply_time = models.DateTimeField(null=True, blank=True)

    def unlock(self) -> bool:
        from NEMO import interlocks

        return interlocks.get(self.card.category).unlock(self)

    def lock(self) -> bool:
        from NEMO import interlocks

        return interlocks.get(self.card.category).lock(self)

    class Meta:
        ordering = ["card__server", "card__number", "channel"]

    def __str__(self):
        from NEMO import interlocks

        category = self.card.category if self.card else None
        channel_name = interlocks.get(category, raise_exception=False).channel_name
        unit_id_name = interlocks.get(category, raise_exception=False).unit_id_name
        display_name = ""
        if self.name:
            display_name += f"{self.name}"
        if self.channel:
            if self.name:
                display_name += ", "
            display_name += f"{channel_name} " + str(self.channel)
        if self.unit_id:
            if self.name or self.channel:
                display_name += ", "
            display_name += f"{unit_id_name} " + str(self.unit_id)
        return str(self.card) + (f", {display_name}" if display_name else "")


class InterlockCardCategory(BaseModel):
    name = models.CharField(max_length=CHAR_FIELD_MEDIUM_LENGTH, help_text="The name for this interlock category")
    key = models.CharField(
        max_length=CHAR_FIELD_SMALL_LENGTH, help_text="The key to identify this interlock category by in interlocks.py"
    )

    class Meta:
        verbose_name_plural = "Interlock card categories"
        ordering = ["name"]

    def __str__(self):
        return str(self.name)


class Task(BaseModel):
    class Urgency(object):
        LOW = -1
        NORMAL = 0
        HIGH = 1
        Choices = (
            (LOW, "Low"),
            (NORMAL, "Normal"),
            (HIGH, "High"),
        )

    urgency = models.IntegerField(choices=Urgency.Choices)
    tool = models.ForeignKey(Tool, help_text="The tool that this task relates to.", on_delete=models.CASCADE)
    force_shutdown = models.BooleanField(
        default=None,
        help_text="Indicates that the tool this task relates to will be shutdown until the task is resolved.",
    )
    safety_hazard = models.BooleanField(default=None, help_text="Indicates that this task represents a safety hazard.")
    creator = models.ForeignKey(
        User, related_name="created_tasks", help_text="The user who created the task.", on_delete=models.CASCADE
    )
    creation_time = models.DateTimeField(default=timezone.now, help_text="The date and time when the task was created.")
    problem_category = models.ForeignKey(
        "TaskCategory", null=True, blank=True, related_name="problem_category", on_delete=models.SET_NULL
    )
    problem_description = models.TextField(blank=True, null=True)
    progress_description = models.TextField(blank=True, null=True)
    last_updated = models.DateTimeField(
        null=True,
        blank=True,
        help_text="The last time this task was modified. (Creating the task does not count as modifying it.)",
    )
    last_updated_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        help_text="The last user who modified this task. This should always be a staff member.",
        on_delete=models.SET_NULL,
    )
    estimated_resolution_time = models.DateTimeField(
        null=True, blank=True, help_text="The estimated date and time that the task will be resolved."
    )
    cancelled = models.BooleanField(default=False)
    resolved = models.BooleanField(default=False)
    resolution_time = models.DateTimeField(
        null=True, blank=True, help_text="The timestamp of when the task was marked complete or cancelled."
    )
    resolver = models.ForeignKey(
        User,
        null=True,
        blank=True,
        related_name="task_resolver",
        help_text="The staff member who resolved the task.",
        on_delete=models.SET_NULL,
    )
    resolution_description = models.TextField(blank=True, null=True)
    resolution_category = models.ForeignKey(
        "TaskCategory", null=True, blank=True, related_name="resolution_category", on_delete=models.SET_NULL
    )

    class Meta:
        ordering = ["-creation_time"]

    def __str__(self):
        return str(self.id)

    def current_status(self):
        """Returns the textual description of the current task status"""
        try:
            return TaskHistory.objects.filter(task_id=self.id).latest().status
        except TaskHistory.DoesNotExist:
            return None

    def task_images(self):
        return TaskImages.objects.filter(task=self).order_by()


class TaskImages(BaseModel):
    task = models.ForeignKey(Task, on_delete=models.CASCADE)
    image = models.ImageField(upload_to=get_task_image_filename, verbose_name="Image")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def filename(self):
        return os.path.basename(self.image.name)

    class Meta:
        verbose_name_plural = "Task images"
        ordering = ["-uploaded_at"]


# These two auto-delete tool images from filesystem when they are unneeded:
@receiver(models.signals.post_delete, sender=Tool)
def auto_delete_file_on_tool_delete(sender, instance: Tool, **kwargs):
    """Deletes file from filesystem when corresponding `Tool` object is deleted."""
    if instance.image:
        if os.path.isfile(instance.image.path):
            os.remove(instance.image.path)


@receiver(models.signals.pre_save, sender=Tool)
def auto_delete_file_on_tool_change(sender, instance: Tool, **kwargs):
    """Deletes old file from filesystem when corresponding `Tool` object is updated with new file."""
    if not instance.pk:
        return False

    try:
        old_file = Tool.objects.get(pk=instance.pk).image
    except Tool.DoesNotExist:
        return False

    if old_file:
        new_file = instance.image
        if not old_file == new_file:
            if os.path.isfile(old_file.path):
                os.remove(old_file.path)


# These two auto-delete task images from filesystem when they are unneeded:
@receiver(models.signals.post_delete, sender=TaskImages)
def auto_delete_file_on_delete(sender, instance: TaskImages, **kwargs):
    """Deletes file from filesystem when corresponding `TaskImages` object is deleted."""
    if instance.image:
        if os.path.isfile(instance.image.path):
            os.remove(instance.image.path)


@receiver(models.signals.pre_save, sender=TaskImages)
def auto_delete_file_on_change(sender, instance: TaskImages, **kwargs):
    """Deletes old file from filesystem when corresponding `TaskImages` object is updated with new file."""
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


class TaskCategory(BaseModel):
    class Stage(object):
        INITIAL_ASSESSMENT = 0
        COMPLETION = 1
        Choices = (
            (INITIAL_ASSESSMENT, "Initial assessment"),
            (COMPLETION, "Completion"),
        )

    name = models.CharField(max_length=CHAR_FIELD_SMALL_LENGTH)
    stage = models.IntegerField(choices=Stage.Choices)

    class Meta:
        verbose_name_plural = "Task categories"
        ordering = ["name"]

    def __str__(self):
        return str(self.name)


class TaskStatus(SerializationByNameModel):
    name = models.CharField(max_length=CHAR_FIELD_MEDIUM_LENGTH, unique=True)
    notify_primary_tool_owner = models.BooleanField(
        default=False, help_text="Notify the primary tool owner when a task transitions to this status"
    )
    notify_backup_tool_owners = models.BooleanField(
        default=False, help_text="Notify the backup tool owners when a task transitions to this status"
    )
    notify_tool_notification_email = models.BooleanField(
        default=False,
        help_text="Send an email to the tool notification email address when a task transitions to this status",
    )
    custom_notification_email_address = models.EmailField(
        blank=True,
        help_text="Notify a custom email address when a task transitions to this status. Leave this blank if you don't need it.",
    )
    notification_message = models.TextField(blank=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = "task statuses"
        ordering = ["name"]


class TaskHistory(BaseModel):
    task = models.ForeignKey(
        Task,
        help_text="The task that this historical entry refers to",
        related_name="history",
        on_delete=models.CASCADE,
    )
    status = models.CharField(max_length=CHAR_FIELD_MEDIUM_LENGTH, help_text="A text description of the task's status")
    time = models.DateTimeField(auto_now_add=True, help_text="The date and time when the task status was changed")
    user = models.ForeignKey(User, help_text="The user that changed the task to this status", on_delete=models.CASCADE)

    class Meta:
        verbose_name_plural = "task histories"
        ordering = ["time"]
        get_latest_by = "time"


class Comment(BaseModel):
    tool = models.ForeignKey(Tool, help_text="The tool that this comment relates to.", on_delete=models.CASCADE)
    author = models.ForeignKey(User, on_delete=models.CASCADE)
    creation_date = models.DateTimeField(default=timezone.now)
    expiration_date = models.DateTimeField(
        blank=True, null=True, help_text="The comment will only be visible until this date."
    )
    visible = models.BooleanField(default=True)
    hide_date = models.DateTimeField(
        blank=True,
        null=True,
        help_text="The date when this comment was hidden. If it is still visible or has expired then this date should be empty.",
    )
    hidden_by = models.ForeignKey(
        User, null=True, blank=True, related_name="hidden_comments", on_delete=models.SET_NULL
    )
    content = models.TextField()
    staff_only = models.BooleanField(default=False)

    class Meta:
        ordering = ["-creation_date"]

    def __str__(self):
        return str(self.id)


class ResourceCategory(BaseModel):
    name = models.CharField(max_length=CHAR_FIELD_MEDIUM_LENGTH)

    def __str__(self):
        return str(self.name)

    class Meta:
        verbose_name_plural = "resource categories"
        ordering = ["name"]


class Resource(BaseModel):
    name = models.CharField(max_length=CHAR_FIELD_MEDIUM_LENGTH)
    category = models.ForeignKey(ResourceCategory, blank=True, null=True, on_delete=models.SET_NULL)
    available = models.BooleanField(default=True, help_text="Indicates whether the resource is available to be used.")
    fully_dependent_tools = models.ManyToManyField(
        Tool,
        blank=True,
        related_name="required_resource_set",
        help_text="These tools will be completely inoperable if the resource is unavailable.",
    )
    partially_dependent_tools = models.ManyToManyField(
        Tool,
        blank=True,
        related_name="nonrequired_resource_set",
        help_text="These tools depend on this resource but can operated at a reduced capacity if the resource is unavailable.",
    )
    dependent_areas = models.ManyToManyField(
        Area,
        blank=True,
        related_name="required_resources",
        help_text="Users will not be able to login to these areas when the resource is unavailable.",
    )
    restriction_message = models.TextField(
        blank=True,
        help_text="The message that is displayed to users on the tool control page when this resource is unavailable.",
    )

    class Meta:
        ordering = ["name"]

    def visible_fully_dependent_tools(self):
        return self.fully_dependent_tools.filter(visible=True)

    def visible_partially_dependent_tools(self):
        return self.partially_dependent_tools.filter(visible=True)

    def __str__(self):
        return self.name


class ActivityHistory(BaseModel):
    """
    Stores the history of when accounts, projects, and users are active.
    This class uses generic relations in order to point to any model type.
    For more information see: https://docs.djangoproject.com/en/dev/ref/contrib/contenttypes/#generic-relations
    """

    class Action(object):
        ACTIVATED = True
        DEACTIVATED = False
        Choices = (
            (ACTIVATED, "Activated"),
            (DEACTIVATED, "Deactivated"),
        )

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")
    action = models.BooleanField(
        choices=Action.Choices, default=None, help_text="The target state (activated or deactivated)."
    )
    date = models.DateTimeField(default=timezone.now, help_text="The time at which the active state was changed.")
    authorizer = models.ForeignKey(
        User,
        help_text="The staff member who changed the active state of the account, project, or user in question.",
        on_delete=models.CASCADE,
    )

    class Meta:
        ordering = ["-date"]
        verbose_name_plural = "activity histories"

    def __str__(self):
        if self.action:
            state = "activated"
        else:
            state = "deactivated"
        return str(self.content_type).capitalize() + " " + str(self.object_id) + " " + state


class MembershipHistory(BaseModel):
    """
    Stores the history of membership between related items. For example, users can be members of projects.
    Likewise, projects can belong to accounts. This class uses generic relations in order to point to any model type.
    For more information see: https://docs.djangoproject.com/en/dev/ref/contrib/contenttypes/#generic-relations
    """

    class Action(object):
        ADDED = True
        REMOVED = False
        Choices = (
            (ADDED, "Added"),
            (REMOVED, "Removed"),
        )

    # The parent entity can be either an account or project.
    parent_content_type = models.ForeignKey(ContentType, related_name="parent_content_type", on_delete=models.CASCADE)
    parent_object_id = models.PositiveIntegerField()
    parent_content_object = GenericForeignKey("parent_content_type", "parent_object_id")

    # The child entity can be either a project or user.
    child_content_type = models.ForeignKey(ContentType, related_name="child_content_type", on_delete=models.CASCADE)
    child_object_id = models.PositiveIntegerField()
    child_content_object = GenericForeignKey("child_content_type", "child_object_id")

    date = models.DateTimeField(default=timezone.now, help_text="The time at which the membership status was changed.")
    authorizer = models.ForeignKey(
        User,
        help_text="The staff member who changed the membership status of the account, project, or user in question.",
        on_delete=models.CASCADE,
    )
    action = models.BooleanField(choices=Action.Choices, default=None)

    class Meta:
        ordering = ["-date"]
        verbose_name_plural = "membership histories"

    def __str__(self):
        return "Membership change for " + str(self.parent_content_type) + " " + str(self.parent_object_id)

    def get_child_content_object(self):
        if self.child_content_object is None:
            return "<deleted>"
        else:
            return str(self.child_content_object)

    def get_parent_content_object(self):
        if self.parent_content_object is None:
            return "<deleted>"
        else:
            return str(self.parent_content_object)


def calculate_duration(start, end, unfinished_reason):
    """
    Calculates the duration between two timestamps. If 'end' is None (thereby
    yielding the calculation impossible) then 'unfinished_reason' is returned.
    """
    if start is None or end is None:
        return unfinished_reason
    else:
        return end - start


class Door(BaseModel):
    name = models.CharField(max_length=CHAR_FIELD_SMALL_LENGTH)
    welcome_message = models.TextField(
        null=True,
        blank=True,
        help_text="The welcome message will be displayed on the tablet login page. You can use HTML and JavaScript.",
    )
    farewell_message = models.TextField(
        null=True,
        blank=True,
        help_text="The farewell message will be displayed on the tablet logout page. You can use HTML and JavaScript.",
    )
    areas = TreeManyToManyField(Area, related_name="doors", blank=False)
    interlock = models.OneToOneField(Interlock, null=True, blank=True, on_delete=models.PROTECT)

    def __str__(self):
        return str(self.name)

    def get_absolute_url(self):
        from django.urls import reverse

        return reverse("welcome_screen", args=[self.id])

    get_absolute_url.short_description = "URL"


class SafetyIssue(BaseModel):
    reporter = models.ForeignKey(
        User, blank=True, null=True, related_name="reported_safety_issues", on_delete=models.SET_NULL
    )
    location = models.CharField(null=True, blank=True, max_length=CHAR_FIELD_MEDIUM_LENGTH)
    creation_time = models.DateTimeField(auto_now_add=True)
    visible = models.BooleanField(
        default=True,
        help_text="Should this safety issue be visible to all users? When unchecked, the issue is only visible to staff.",
    )
    concern = models.TextField()
    progress = models.TextField(blank=True, null=True)
    resolution = models.TextField(blank=True, null=True)
    resolved = models.BooleanField(default=False)
    resolution_time = models.DateTimeField(blank=True, null=True)
    resolver = models.ForeignKey(
        User, related_name="resolved_safety_issues", blank=True, null=True, on_delete=models.SET_NULL
    )

    class Meta:
        ordering = ["-creation_time"]

    def __str__(self):
        return str(self.id)

    def get_absolute_url(self):
        from django.urls import reverse

        return reverse("update_safety_issue", args=[self.id])


class SafetyCategory(BaseCategory):
    class Meta(BaseCategory.Meta):
        verbose_name_plural = "Safety categories"


class SafetyItem(BaseModel):
    name = models.CharField(max_length=CHAR_FIELD_MEDIUM_LENGTH, help_text="The safety item name.")
    description = models.TextField(
        null=True, blank=True, help_text="The description for this safety item. HTML can be used."
    )
    category = models.ForeignKey(
        SafetyCategory, null=True, blank=True, help_text="The category for this safety item.", on_delete=models.SET_NULL
    )
    display_order = models.IntegerField(
        help_text="The order in which the items will be displayed within the same category. Lower values are displayed first."
    )

    def __str__(self):
        return self.name

    class Meta:
        ordering = ["display_order", "name"]


class SafetyItemDocuments(BaseDocumentModel):
    safety_item = models.ForeignKey(SafetyItem, on_delete=models.CASCADE)

    def get_filename_upload(self, filename):
        from django.template.defaultfilters import slugify

        item_name = slugify(self.safety_item.name)
        return f"safety_item/{item_name}/{filename}"

    class Meta(BaseDocumentModel.Meta):
        verbose_name_plural = "Safety item documents"


class AlertCategory(BaseModel):
    name = models.CharField(max_length=CHAR_FIELD_MEDIUM_LENGTH)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "Alert categories"

    def __str__(self):
        return self.name


class Alert(BaseModel):
    title = models.CharField(blank=True, max_length=CHAR_FIELD_MEDIUM_LENGTH)
    category = models.CharField(
        blank=True, max_length=CHAR_FIELD_MEDIUM_LENGTH, help_text="A category/type for this alert."
    )
    contents = models.TextField()
    creation_time = models.DateTimeField(default=timezone.now)
    creator = models.ForeignKey(User, null=True, blank=True, related_name="+", on_delete=models.SET_NULL)
    debut_time = models.DateTimeField(
        help_text="The alert will not be displayed to users until the debut time is reached."
    )
    expiration_time = models.DateTimeField(
        null=True, blank=True, help_text="The alert can be deleted after the expiration time is reached."
    )
    user = models.ForeignKey(
        User,
        null=True,
        blank=True,
        related_name="alerts",
        help_text="The alert will be visible for this user. The alert is visible to all users when this is empty.",
        on_delete=models.CASCADE,
    )
    dismissible = models.BooleanField(
        default=False, help_text="Allows the user to delete the alert. This is only valid when the 'user' field is set."
    )
    expired = models.BooleanField(default=False, help_text="Indicates the alert has expired and won't be shown anymore")
    deleted = models.BooleanField(
        default=False, help_text="Indicates the alert has been deleted and won't be shown anymore"
    )

    def clean(self):
        if self.dismissible and not self.user:
            raise ValidationError({"dismissible": "Only a user-specific alert can be dismissed by the user"})

    class Meta:
        ordering = ["-debut_time"]

    def __str__(self):
        return str(self.id)


class ContactInformationCategory(BaseCategory):
    class Meta(BaseCategory.Meta):
        verbose_name_plural = "Contact information categories"


class ContactInformation(BaseModel):
    name = models.CharField(max_length=CHAR_FIELD_MEDIUM_LENGTH)
    title = models.CharField(max_length=CHAR_FIELD_MEDIUM_LENGTH, blank=True, null=True)
    image = models.ImageField(
        blank=True,
        help_text="Portraits are resized to 266 pixels high and 200 pixels wide. Crop portraits to these dimensions before uploading for optimal bandwidth usage",
    )
    category = models.ForeignKey(ContactInformationCategory, on_delete=models.CASCADE)
    email = models.EmailField(blank=True)
    office_phone = models.CharField(max_length=40, blank=True)
    office_location = models.CharField(max_length=CHAR_FIELD_MEDIUM_LENGTH, blank=True)
    mobile_phone = models.CharField(max_length=40, blank=True)
    mobile_phone_is_sms_capable = models.BooleanField(
        default=True,
        verbose_name="Mobile phone is SMS capable",
        help_text="Is the mobile phone capable of receiving text messages? If so, a link will be displayed for users to click to send a text message to the recipient when viewing the 'Contact information' page.",
    )
    user = models.OneToOneField(
        to=User,
        blank=True,
        null=True,
        help_text="Select a user to associate with this contact. When set, this contact information will be shown instead of the user information on pages like tool details.",
        on_delete=models.CASCADE,
    )

    class Meta:
        verbose_name_plural = "Contact information"
        ordering = ["name"]

    def __str__(self):
        return str(self.name)


class Notification(BaseModel):
    class Types:
        NEWS = "news"
        SAFETY = "safetyissue"
        BUDDY_REQUEST = "buddyrequest"
        BUDDY_REQUEST_REPLY = "buddyrequestmessage"
        ADJUSTMENT_REQUEST = "adjustmentrequest"
        ADJUSTMENT_REQUEST_REPLY = "adjustmentrequestmessage"
        TEMPORARY_ACCESS_REQUEST = "temporaryphysicalaccessrequest"
        Choices = (
            (NEWS, "News creation and updates - notifies all users"),
            (SAFETY, "New safety issues - notifies staff only"),
            (BUDDY_REQUEST, "New buddy request - notifies all users"),
            (BUDDY_REQUEST_REPLY, "New buddy request reply - notifies request creator and users who have replied"),
            (ADJUSTMENT_REQUEST, "New adjustment request - notifies reviewers only"),
            (
                ADJUSTMENT_REQUEST_REPLY,
                "New adjustment request reply - notifies request creator and users who have replied",
            ),
            (TEMPORARY_ACCESS_REQUEST, "New access request - notifies other users on request and reviewers"),
        )

    user = models.ForeignKey(User, related_name="notifications", on_delete=models.CASCADE)
    expiration = models.DateTimeField()
    notification_type = models.CharField(max_length=CHAR_FIELD_SMALL_LENGTH, choices=Types.Choices)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")


class LandingPageChoice(BaseModel):
    image = models.ImageField(
        help_text="An image that symbolizes the choice. It is automatically resized to 128x128 pixels when displayed, so set the image to this size before uploading to optimize bandwidth usage and landing page load time"
    )
    name = models.CharField(
        max_length=CHAR_FIELD_SMALL_LENGTH, help_text="The textual name that will be displayed underneath the image"
    )
    url = models.URLField(
        verbose_name="URL",
        help_text="The URL that the choice leads to when clicked. Relative paths such as /calendar/ are used when linking within the site. Use fully qualified URL paths such as https://www.google.com/ to link to external sites.",
    )
    display_order = models.IntegerField(
        help_text="The order in which choices are displayed on the landing page, from left to right, top to bottom. Lower values are displayed first."
    )
    open_in_new_tab = models.BooleanField(
        default=False, help_text="Open the URL in a new browser tab when it's clicked"
    )
    secure_referral = models.BooleanField(
        default=True,
        help_text="Improves security by blocking HTTP referer [sic] information from the targeted page. Enabling this prevents the target page from manipulating the calling page's DOM with JavaScript. This should always be used for external links. It is safe to uncheck this when linking within the site. Leave this box checked if you don't know what this means",
    )
    hide_from_mobile_devices = models.BooleanField(
        default=False, help_text="Hides this choice when the landing page is viewed from a mobile device"
    )
    hide_from_desktop_computers = models.BooleanField(
        default=False, help_text="Hides this choice when the landing page is viewed from a desktop computer"
    )
    hide_from_users = models.BooleanField(
        default=False,
        help_text="Hides this choice from normal users. When checked, only staff, technicians, facility managers and super-users can see the choice",
    )
    hide_from_staff = models.BooleanField(
        default=False,
        help_text="Hides this choice from staff and technicians. When checked, only normal users, facility managers and super-users can see the choice",
    )
    notifications = models.CharField(
        max_length=CHAR_FIELD_SMALL_LENGTH,
        blank=True,
        null=True,
        choices=Notification.Types.Choices,
        help_text="Displays a the number of new notifications for the user. For example, if the user has two unread news notifications then the number '2' would appear for the news icon on the landing page.",
    )

    class Meta:
        ordering = ["display_order"]

    def __str__(self):
        return str(self.name)


class Customization(BaseModel):
    name = models.CharField(primary_key=True, max_length=CHAR_FIELD_SMALL_LENGTH)
    value = models.TextField()

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return str(self.name)


class ScheduledOutageCategory(BaseModel):
    name = models.CharField(max_length=CHAR_FIELD_MEDIUM_LENGTH)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "Scheduled outage categories"

    def __str__(self):
        return self.name


class ScheduledOutage(BaseModel):
    start = models.DateTimeField()
    end = models.DateTimeField()
    creator = models.ForeignKey(User, on_delete=models.CASCADE)
    title = models.CharField(
        max_length=CHAR_FIELD_SMALL_LENGTH, help_text="A brief description to quickly inform users about the outage"
    )
    details = models.TextField(
        blank=True,
        help_text="A detailed description of why there is a scheduled outage, and what users can expect during the outage",
    )
    category = models.CharField(
        blank=True,
        max_length=CHAR_FIELD_MEDIUM_LENGTH,
        help_text="A categorical reason for why this outage is scheduled. Useful for trend analytics.",
    )
    tool = models.ForeignKey(Tool, blank=True, null=True, on_delete=models.CASCADE)
    area = TreeForeignKey(Area, blank=True, null=True, on_delete=models.CASCADE)
    resource = models.ForeignKey(Resource, blank=True, null=True, on_delete=models.CASCADE)
    reminder_days = models.CharField(
        null=True,
        blank=True,
        max_length=CHAR_FIELD_MEDIUM_LENGTH,
        validators=[validate_comma_separated_integer_list],
        help_text="The number of days to send a reminder before a scheduled outage. A comma-separated list can be used for multiple reminders.",
    )
    reminder_emails: List[str] = fields.MultiEmailField(
        null=True,
        blank=True,
        help_text="The reminder email(s) will be sent to this address. A comma-separated list can be used.",
    )

    @property
    def outage_item(self) -> Union[Tool, Area, Resource]:
        return self.tool or self.area or self.resource

    @outage_item.setter
    def outage_item(self, item):
        if isinstance(item, Tool):
            self.tool = item
        elif isinstance(item, Area):
            self.area = item
        elif isinstance(item, Resource):
            self.resource = item
        else:
            raise AttributeError(f"This item [{item}] isn't allowed on outages.")

    @property
    def outage_item_type(self) -> ReservationItemType:
        if self.tool:
            return ReservationItemType.TOOL
        elif self.area:
            return ReservationItemType.AREA

    @property
    def outage_item_filter(self):
        if not self.outage_item_type:
            return {"tool": None, "area": None}
        else:
            return {self.outage_item_type.value: self.outage_item}

    def has_not_ended(self):
        return False if self.end < timezone.now() else True

    def has_not_started(self):
        return False if self.start <= timezone.now() else True

    def get_reminder_days(self) -> List[int]:
        if not self.reminder_emails:
            return []
        return [int(days) for days in self.reminder_days.split(",")]

    def clean(self):
        if self.start and self.end and self.start >= self.end:
            raise ValidationError(
                {
                    "start": "Outage start time ("
                    + format_datetime(self.start)
                    + ") must be before the end time ("
                    + format_datetime(self.end)
                    + ")."
                }
            )

    def __str__(self):
        return str(self.title)


class News(BaseModel):
    title = models.CharField(max_length=CHAR_FIELD_MEDIUM_LENGTH)
    pinned = models.BooleanField(
        default=False, help_text="Check this box to keep this story at the top of the news feed"
    )
    created = models.DateTimeField(help_text="The date and time this story was first published")
    original_content = models.TextField(
        help_text="The content of the story when it was first published, useful for visually hiding updates 'in the middle' of the story"
    )
    all_content = models.TextField(help_text="The entire content of the story")
    last_updated = models.DateTimeField(help_text="The date and time this story was last updated")
    last_update_content = models.TextField(
        help_text="The most recent update to the story, useful for visually hiding updates 'in the middle' of the story"
    )
    archived = models.BooleanField(
        default=False, help_text="A story is removed from the 'Recent News' page when it is archived"
    )
    update_count = models.PositiveIntegerField(
        help_text="The number of times this story has been updated. When the number of updates is greater than 2, then only the original story and the latest update are displayed in the 'Recent News' page"
    )

    class Meta:
        ordering = ["-last_updated"]
        verbose_name_plural = "News"


class BadgeReader(BaseModel):
    name = models.CharField(max_length=CHAR_FIELD_MEDIUM_LENGTH)
    send_key = models.CharField(
        max_length=20,
        help_text="The name of the key which submits the badge number ('F2', 'Shift', 'Meta', 'Enter', 'a' etc.)",
    )
    record_key = models.CharField(
        null=True,
        blank=True,
        max_length=20,
        help_text="The name of the key which starts badge number recording. If left blank, badge number recording starts when any input is received.",
    )

    def __str__(self):
        return str(self.name)

    @staticmethod
    def default():
        # The default badge reader is a badge reader using F2 for recording and sending
        default_badge_reader = BadgeReader()
        default_badge_reader.record_key = "F2"
        default_badge_reader.send_key = "F2"
        return default_badge_reader


class ToolUsageCounter(BaseModel):
    class CounterDirection(object):
        INCREMENT = +1
        DECREMENT = -1
        Choices = (
            (INCREMENT, _("Increment")),
            (DECREMENT, _("Decrement")),
        )

    name = models.CharField(max_length=CHAR_FIELD_MEDIUM_LENGTH, help_text=_("The name of this counter"))
    description = models.TextField(
        null=True,
        blank=True,
        help_text=_("The counter description to be displayed next to it on the tool control page"),
    )
    value = models.FloatField(help_text=_("The current value of this counter"))
    default_value = models.FloatField(help_text=_("The default value to reset this counter to"))
    counter_direction = models.IntegerField(default=CounterDirection.INCREMENT, choices=CounterDirection.Choices)
    tool = models.ForeignKey(Tool, help_text=_("The tool this counter is for."), on_delete=models.CASCADE)
    tool_usage_question = models.CharField(
        max_length=CHAR_FIELD_MEDIUM_LENGTH,
        help_text=_("The name of the tool's post usage question which should be used to increment this counter"),
    )
    staff_members_can_reset = models.BooleanField(
        default=True, help_text=_("Check this box to allow staff to reset this counter")
    )
    superusers_can_reset = models.BooleanField(
        default=False, help_text=_("Check this box to allow tool superusers to reset this counter")
    )
    qualified_users_can_reset = models.BooleanField(
        default=False, help_text=_("Check this box to allow qualified users to reset this counter")
    )
    last_reset_value = models.FloatField(
        null=True, blank=True, help_text=_("The last value before the counter was reset")
    )
    last_reset = models.DateTimeField(
        null=True, blank=True, help_text=_("The date and time this counter was last reset")
    )
    last_reset_by = models.ForeignKey(
        User, null=True, blank=True, help_text=_("The user who last reset this counter"), on_delete=models.SET_NULL
    )
    email_facility_managers_when_reset = models.BooleanField(
        default=True, help_text=_("Check this box to email facility managers when this counter is reset")
    )
    warning_threshold = models.FloatField(
        null=True,
        blank=True,
        help_text=_(
            "When set in combination with the email address, a warning email will be sent when the counter reaches this value."
        ),
    )
    warning_email = fields.MultiEmailField(
        null=True,
        blank=True,
        help_text=_("The address to send the warning email to. A comma-separated list can be used."),
    )
    warning_threshold_reached = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True, help_text=_("The state of the counter"))

    def value_color(self):
        color = None
        if self.warning_threshold:
            effective_value = self.counter_direction * self.value
            effective_warning_threshold = self.counter_direction * self.warning_threshold
            if effective_value < effective_warning_threshold:
                color = "success"
            elif effective_value == effective_warning_threshold:
                color = "warning"
            elif effective_value > effective_warning_threshold:
                color = "danger"
        return bootstrap_primary_color(color)

    def reset_permitted_users(self) -> QuerySetType[User]:
        user_filter = Q(is_facility_manager=True) | Q(is_superuser=True)
        if self.staff_members_can_reset:
            user_filter |= Q(is_staff=True)
        if self.superusers_can_reset:
            user_filter |= Q(superuser_for_tools__in=[self.tool])
        if self.qualified_users_can_reset:
            user_filter |= Q(id__in=Qualification.objects.filter(tool=self.tool).values_list("user_id", flat=True))
        return User.objects.filter(Q(is_active=True) & user_filter).distinct()

    def clean(self):
        errors = {}
        if self.warning_threshold:
            effective_warning_threshold = self.counter_direction * self.warning_threshold
            effective_default_value = self.counter_direction * self.default_value
            if effective_default_value > effective_warning_threshold:
                errors.update(
                    {
                        "warning_threshold": _(
                            f"The warning threshold ({self.warning_threshold}) needs to be {'higher' if self.counter_direction > 0 else 'lower'} than the default value ({self.default_value})"
                        )
                    }
                )
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return str(self.name)

    class Meta:
        ordering = ["tool__name"]


# This method is used to check when a tool usage counter value gets over the threshold
@receiver(models.signals.pre_save, sender=ToolUsageCounter)
def check_tool_usage_counter_threshold(sender, instance: ToolUsageCounter, **kwargs):
    try:
        if instance.warning_threshold:
            effective_warning_threshold = instance.counter_direction * instance.warning_threshold
            effective_value = instance.counter_direction * instance.value
            if (
                instance.is_active
                and not instance.warning_threshold_reached
                and effective_value >= effective_warning_threshold
            ):
                # value is under/over threshold. set flag and send email
                instance.warning_threshold_reached = True
                from NEMO.views.tool_control import send_tool_usage_counter_email

                send_tool_usage_counter_email(instance)
            if instance.warning_threshold_reached and effective_value < effective_warning_threshold:
                # it has been reset. reset flag
                instance.warning_threshold_reached = False
    except Exception as e:
        models_logger.exception(e)
        pass


class BuddyRequest(BaseModel):
    creation_time = models.DateTimeField(
        default=timezone.now, help_text="The date and time when the request was created."
    )
    start = models.DateField(help_text="The start date the user is requesting a buddy.")
    end = models.DateField(help_text="The end date the user is requesting a buddy.")
    description = models.TextField(help_text="The description of the request.")
    area = models.ForeignKey(Area, on_delete=models.CASCADE)
    user = models.ForeignKey(User, help_text="The user who is submitting the request.", on_delete=models.CASCADE)
    expired = models.BooleanField(
        default=False, help_text="Indicates the request has expired and won't be shown anymore."
    )
    deleted = models.BooleanField(
        default=False, help_text="Indicates the request has been deleted and won't be shown anymore."
    )

    @property
    def creator(self) -> User:
        return self.user

    @property
    def replies(self) -> QuerySetType[RequestMessage]:
        return RequestMessage.objects.filter(object_id=self.id, content_type=ContentType.objects.get_for_model(self))

    def creator_and_reply_users(self) -> List[User]:
        result = {self.user}
        for reply in self.replies:
            result.add(reply.author)
        return list(result)

    def __str__(self):
        return f"BuddyRequest [{self.id}]"


class AdjustmentRequest(BaseModel):
    creation_time = models.DateTimeField(auto_now_add=True, help_text="The date and time when the request was created.")
    creator = models.ForeignKey("User", related_name="adjustment_requests_created", on_delete=models.CASCADE)
    last_updated = models.DateTimeField(auto_now=True, help_text="The last time this request was modified.")
    last_updated_by = models.ForeignKey(
        "User",
        null=True,
        blank=True,
        related_name="adjustment_requests_updated",
        help_text="The last user who modified this request.",
        on_delete=models.SET_NULL,
    )
    item_type = models.ForeignKey(ContentType, null=True, blank=True, on_delete=models.CASCADE)
    item_id = models.PositiveIntegerField(null=True, blank=True)
    item = GenericForeignKey("item_type", "item_id")
    description = models.TextField(null=True, blank=True, help_text="The description of the request.")
    manager_note = models.TextField(
        null=True,
        blank=True,
        help_text="A manager's note to send to the user when a request is denied or to the user office when it is approved.",
    )
    new_start = models.DateTimeField(null=True, blank=True)
    new_end = models.DateTimeField(null=True, blank=True)
    new_quantity = models.PositiveIntegerField(null=True, blank=True)
    waive = models.BooleanField(default=False)
    status = models.IntegerField(choices=RequestStatus.choices_without_expired(), default=RequestStatus.PENDING)
    reviewer = models.ForeignKey(
        "User", null=True, blank=True, related_name="adjustment_requests_reviewed", on_delete=models.CASCADE
    )
    applied = models.BooleanField(default=False, help_text="Indicates the adjustment has been applied")
    applied_by = models.ForeignKey(
        "User", null=True, blank=True, related_name="adjustment_requests_applied", on_delete=models.CASCADE
    )
    deleted = models.BooleanField(
        default=False, help_text="Indicates the request has been deleted and won't be shown anymore."
    )

    @property
    def replies(self) -> QuerySetType[RequestMessage]:
        return RequestMessage.objects.filter(object_id=self.id, content_type=ContentType.objects.get_for_model(self))

    def get_new_start(self) -> Optional[datetime]:
        # Returns the new start if different from the item's start (not counting seconds and microseconds)
        return (
            self.new_start
            if self.new_start
            and self.item
            and self.item.start
            and self.item.start.replace(microsecond=0, second=0) != self.new_start
            else None
        )

    def get_new_end(self) -> Optional[datetime]:
        # Returns the new end if different from the item's end (not counting seconds and microseconds)
        return (
            self.new_end
            if self.new_end
            and self.item
            and self.item.end
            and self.item.end.replace(microsecond=0, second=0) != self.new_end
            else None
        )

    def get_quantity_difference(self) -> int:
        if self.item and self.new_quantity is not None:
            return self.new_quantity - self.item.quantity

    def get_time_difference(self) -> str:
        if self.item and self.new_start and self.new_end:
            previous_duration = self.item.end.replace(microsecond=0, second=0) - self.item.start.replace(
                microsecond=0, second=0
            )
            new_duration = self.new_end - self.new_start
            return (
                f"+{(new_duration - previous_duration)}"
                if new_duration >= previous_duration
                else f"- {(previous_duration - new_duration)}"
            )

    def get_difference(self):
        if self.waive:
            return "Waived" if self.item and self.item.waived else "Waive requested"
        else:
            return (self.get_time_difference() or self.get_quantity_difference()) if self.item else ""

    def adjustable_charge(self):
        return (
            self.waive
            or self.has_changed_time()
            or isinstance(self.item, Reservation)
            or self.get_quantity_difference()
        )

    def has_changed_time(self) -> bool:
        """Returns whether the original charge is editable, i.e. if it has a changed start or end"""
        return self.item and (self.get_new_end() or self.get_new_start())

    def creator_and_reply_users(self) -> List[User]:
        result = {self.creator}
        for reply in self.replies:
            result.add(reply.author)
        result.update(self.reviewers())
        return list(result)

    def reviewers(self) -> QuerySetType[User]:
        # Create the list of users to notify/show request to. If the adjustment request has a tool/area and their
        # list of reviewers is empty, send/show to all facility managers
        item = get_model_instance(self.item_type, self.item_id)
        tool: Tool = getattr(item, "tool", None) if item else None
        area: Area = getattr(item, "area", None) if item else None
        facility_managers = User.objects.filter(is_active=True, is_facility_manager=True)
        if tool:
            tool_reviewers = tool._adjustment_request_reviewers.filter(is_active=True)
            return tool_reviewers or facility_managers
        if area:
            area_reviewers = area.adjustment_request_reviewers.filter(is_active=True)
            return area_reviewers or facility_managers
        return facility_managers

    def apply_adjustment(self, user):
        if self.status == RequestStatus.APPROVED:
            if self.waive:
                self.item.waive(user)
                self.applied = True
                self.applied_by = user
                self.save()
            elif self.has_changed_time():
                new_start = self.get_new_start()
                new_end = self.get_new_end()
                if new_start:
                    self.item.start = new_start
                if new_end:
                    self.item.end = new_end
                self.item.save()
                self.applied = True
                self.applied_by = user
                self.save()
            elif self.get_quantity_difference():
                self.item.quantity = self.new_quantity
                self.item.save()
                self.applied = True
                self.applied_by = user
            elif isinstance(self.item, Reservation):
                # in this case the times have not been changed so we are essentially waiving the charge
                self.waive = True
                self.apply_adjustment(user)

    def delete(self, using=None, keep_parents=False):
        adjustment_id = self.id
        super().delete(using, keep_parents)
        # If adjustment requests is being deleted, remove associated notifications
        Notification.objects.filter(
            object_id=adjustment_id,
            notification_type__in=[
                Notification.Types.ADJUSTMENT_REQUEST,
                Notification.Types.ADJUSTMENT_REQUEST_REPLY,
            ],
        ).delete()

    def save(self, *args, **kwargs):
        # We are removing new start, new end and new quantity just in case
        if self.waive:
            self.new_end = None
            self.new_start = None
            self.new_quantity = None
        super().save(*args, **kwargs)

    def clean(self):
        if not self.description:
            raise ValidationError({"description": _("This field is required.")})
        item = get_model_instance(self.item_type, self.item_id)
        if item:
            already_adjusted = AdjustmentRequest.objects.filter(
                deleted=False, item_type_id=self.item_type_id, item_id=self.item_id
            )
            if self.pk:
                already_adjusted = already_adjusted.exclude(pk=self.pk)
            if already_adjusted.exists():
                raise ValidationError({NON_FIELD_ERRORS: _("There is already an adjustment request for this charge")})
            if self.new_start and self.new_end and self.new_start > self.new_end:
                raise ValidationError({"new_end": _("The end must be later than the start")})

    class Meta:
        ordering = ["-creation_time"]


class RequestMessage(BaseModel):
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")
    author = models.ForeignKey(User, on_delete=models.CASCADE)
    creation_date = models.DateTimeField(default=timezone.now)
    content = models.TextField()

    class Meta:
        ordering = ["creation_date"]


class StaffAbsenceType(BaseModel):
    name = models.CharField(max_length=CHAR_FIELD_MEDIUM_LENGTH, help_text="The name of this absence type.")
    description = models.CharField(
        max_length=CHAR_FIELD_MEDIUM_LENGTH, help_text="The description for this absence type."
    )

    def __str__(self):
        description = f" ({self.description})" if self.description else ""
        return f"{self.name}{description}"

    class Meta:
        ordering = ["name"]


class StaffAvailabilityCategory(BaseCategory):
    class Meta(BaseCategory.Meta):
        verbose_name_plural = "Staff availability categories"


class StaffAvailability(BaseModel):
    DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    staff_member = models.ForeignKey(
        "User", help_text="The staff member to display on the staff status page.", on_delete=models.CASCADE
    )
    visible = models.BooleanField(
        default=True, help_text="Specifies whether this staff member should be displayed on the staff status page."
    )
    category = models.ForeignKey(
        StaffAvailabilityCategory,
        null=True,
        blank=True,
        help_text="The category for this staff member.",
        on_delete=models.CASCADE,
    )
    start_time = models.TimeField(null=True, blank=True, help_text="The usual start time for this staff member.")
    end_time = models.TimeField(null=True, blank=True, help_text="The usual end time for this staff member.")
    monday = models.BooleanField(default=True, help_text="Check this box if the staff member usually works on Mondays.")
    tuesday = models.BooleanField(
        default=True, help_text="Check this box if the staff member usually works on Tuesdays."
    )
    wednesday = models.BooleanField(
        default=True, help_text="Check this box if the staff member usually works on Wednesdays."
    )
    thursday = models.BooleanField(
        default=True, help_text="Check this box if the staff member usually works on Thursdays."
    )
    friday = models.BooleanField(default=True, help_text="Check this box if the staff member usually works on Fridays.")
    saturday = models.BooleanField(
        default=False, help_text="Check this box if the staff member usually works on Saturdays."
    )
    sunday = models.BooleanField(
        default=False, help_text="Check this box if the staff member usually works on Sundays."
    )

    def weekly_availability(self, available=True, absent=False) -> dict:
        return {index: available if getattr(self, day) else absent for index, day in enumerate(self.DAYS)}

    def daily_hours(self) -> str:
        if not self.start_time and not self.end_time:
            return ""
        start = format_datetime(self.start_time) if self.start_time else ""
        end = format_datetime(self.end_time) if self.end_time else ""
        return f"Working hours: {format_daterange(self.start_time, self.end_time) if start and end else 'from ' + start if start else 'until '+end}"

    def __str__(self):
        return str(self.staff_member)

    class Meta:
        verbose_name_plural = "Staff availability"
        ordering = ["staff_member__first_name"]


class StaffAbsence(BaseModel):
    creation_time = models.DateTimeField(auto_now_add=True, help_text="The date and time when the absence was created.")
    staff_member = models.ForeignKey(
        StaffAvailability, help_text="The staff member who will be absent.", on_delete=models.CASCADE
    )
    absence_type = models.ForeignKey(
        StaffAbsenceType,
        help_text="The absence type. This will only be visible to facility managers.",
        on_delete=models.CASCADE,
    )
    start_date = models.DateField(help_text="The start date of the absence.")
    end_date = models.DateField(help_text="The end date of the absence.")
    full_day = models.BooleanField(
        default=True, help_text="Uncheck this box when the absence is only for part of the day."
    )
    description = models.TextField(
        null=True, blank=True, help_text="The absence description. This will be visible to anyone."
    )
    manager_note = models.TextField(null=True, blank=True, help_text="A note only visible to managers.")

    def details_for_manager(self):
        dates = f" {format_daterange(self.start_date, self.end_date)}" if self.start_date != self.end_date else ""
        description = f"<br>{linebreaksbr(self.description)}" if self.description else ""
        manager_note = f"<br>{linebreaksbr(self.manager_note)}" if self.manager_note else ""
        return f"{self.absence_type.description}{dates}{description}{manager_note}"

    def clean(self):
        if self.end_date and self.start_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": "The end date must be on or after the start date"})

    class Meta:
        ordering = ["-creation_time"]


class ChemicalHazard(BaseCategory):
    logo = models.ImageField(upload_to=get_hazard_logo_filename, blank=True, help_text="The logo for this hazard")


class Chemical(BaseModel):
    name = models.CharField(max_length=CHAR_FIELD_MEDIUM_LENGTH)
    hazards = models.ManyToManyField(ChemicalHazard, blank=True, help_text="Select the hazards for this chemical.")
    document = models.FileField(null=True, blank=True, upload_to=get_chemical_document_filename, max_length=500)
    url = models.URLField(null=True, blank=True, verbose_name="URL")
    keywords = models.TextField(null=True, blank=True)

    class Meta:
        ordering = ["name"]

    def link(self):
        return self.document.url if self.document else self.url

    def __str__(self):
        return str(self.name)


# These two auto-delete hazard images from filesystem when they are unneeded:
@receiver(models.signals.post_delete, sender=ChemicalHazard)
def auto_delete_file_on_hazard_delete(sender, instance: ChemicalHazard, **kwargs):
    """Deletes file from filesystem when corresponding `ChemicalHazard` object is deleted."""
    if instance.logo:
        if os.path.isfile(instance.logo.path):
            os.remove(instance.logo.path)


@receiver(models.signals.pre_save, sender=ChemicalHazard)
def auto_delete_file_on_hazard_change(sender, instance: ChemicalHazard, **kwargs):
    """Deletes old file from filesystem when corresponding `ChemicalHazard` object is updated with new file."""
    if not instance.pk:
        return False

    try:
        old_file = ChemicalHazard.objects.get(pk=instance.pk).logo
    except ChemicalHazard.DoesNotExist:
        return False

    if old_file:
        new_file = instance.logo
        if not old_file == new_file:
            if os.path.isfile(old_file.path):
                os.remove(old_file.path)


# These two auto-delete chemical document from filesystem when they are unneeded:
@receiver(models.signals.post_delete, sender=Chemical)
def auto_delete_file_on_chemical_delete(sender, instance: Chemical, **kwargs):
    """Deletes file from filesystem when corresponding `Chemical` object is deleted."""
    if instance.document:
        if os.path.isfile(instance.document.path):
            os.remove(instance.document.path)


@receiver(models.signals.pre_save, sender=Chemical)
def auto_delete_file_on_chemical_change(sender, instance: Chemical, **kwargs):
    """Deletes old file from filesystem when corresponding `Chemical` object is updated with new file."""
    if not instance.pk:
        return False

    try:
        old_file = Chemical.objects.get(pk=instance.pk).document
    except Chemical.DoesNotExist:
        return False

    if old_file:
        new_file = instance.document
        if not old_file == new_file:
            if os.path.isfile(old_file.path):
                os.remove(old_file.path)


class StaffKnowledgeBaseCategory(BaseCategory):
    class Meta(BaseCategory.Meta):
        verbose_name_plural = "Staff knowledge base categories"


class StaffKnowledgeBaseItem(BaseModel):
    name = models.CharField(max_length=CHAR_FIELD_MEDIUM_LENGTH, help_text="The item name.")
    description = models.TextField(null=True, blank=True, help_text="The description for this item. HTML can be used.")
    category = models.ForeignKey(
        StaffKnowledgeBaseCategory,
        null=True,
        blank=True,
        help_text="The category for this item.",
        on_delete=models.SET_NULL,
    )
    display_order = models.IntegerField(
        help_text="The order in which the items will be displayed within the same category. Lower values are displayed first."
    )

    def __str__(self):
        return self.name

    class Meta:
        ordering = ["display_order", "name"]


class StaffKnowledgeBaseItemDocuments(BaseDocumentModel):
    item = models.ForeignKey(StaffKnowledgeBaseItem, on_delete=models.CASCADE)

    def get_filename_upload(self, filename):
        from django.template.defaultfilters import slugify

        item_name = slugify(self.item.name)
        return f"{MEDIA_PROTECTED}/knowledge_base/{item_name}/{filename}"

    class Meta(BaseDocumentModel.Meta):
        verbose_name_plural = "Staff knowledge base item documents"


class UserKnowledgeBaseCategory(BaseCategory):
    class Meta(BaseCategory.Meta):
        verbose_name_plural = "User knowledge base categories"


class UserKnowledgeBaseItem(BaseModel):
    name = models.CharField(max_length=CHAR_FIELD_MEDIUM_LENGTH, help_text="The item name.")
    description = models.TextField(null=True, blank=True, help_text="The description for this item. HTML can be used.")
    category = models.ForeignKey(
        UserKnowledgeBaseCategory,
        null=True,
        blank=True,
        help_text="The category for this item.",
        on_delete=models.SET_NULL,
    )
    display_order = models.IntegerField(
        help_text="The order in which the items will be displayed within the same category. Lower values are displayed first."
    )

    def __str__(self):
        return self.name

    class Meta:
        ordering = ["display_order", "name"]


class UserKnowledgeBaseItemDocuments(BaseDocumentModel):
    item = models.ForeignKey(UserKnowledgeBaseItem, on_delete=models.CASCADE)

    def get_filename_upload(self, filename):
        from django.template.defaultfilters import slugify

        item_name = slugify(self.item.name)
        return f"knowledge_base/{item_name}/{filename}"

    class Meta(BaseDocumentModel.Meta):
        verbose_name_plural = "User knowledge base item documents"


class ToolCredentials(BaseModel):
    tool = models.ForeignKey(Tool, on_delete=models.CASCADE)
    username = models.CharField(null=True, blank=True, max_length=CHAR_FIELD_MEDIUM_LENGTH)
    password = models.CharField(null=True, blank=True, max_length=CHAR_FIELD_MEDIUM_LENGTH)
    comments = models.CharField(null=True, blank=True, max_length=CHAR_FIELD_MEDIUM_LENGTH)
    authorized_staff = models.ManyToManyField(
        User,
        blank=True,
        help_text="Selected staff will be the only ones allowed to see these credentials. Leave blank for all staff.",
    )

    class Meta:
        ordering = ["-tool__visible", "tool___category", "tool__name"]
        verbose_name = "Tool credentials"
        verbose_name_plural = "Tool credentials"


class EmailLog(BaseModel):
    category = models.IntegerField(choices=EmailCategory.Choices, default=EmailCategory.GENERAL)
    when = models.DateTimeField(null=False, auto_now_add=True)
    sender = models.EmailField(null=False, blank=False)
    to = models.TextField(null=False, blank=False)
    subject = models.CharField(null=False, max_length=CHAR_FIELD_MEDIUM_LENGTH)
    content = models.TextField(null=False)
    ok = models.BooleanField(null=False, default=True)
    attachments = models.TextField(null=True)

    class Meta:
        ordering = ["-when"]


def validate_waive_information(item: [BillableItemMixin]) -> Dict:
    errors = {}
    if item.waived:
        if not item.waived_by:
            errors["waived_by"] = _("This field is required")
        if not item.waived_on:
            errors["waived_on"] = _("This field is required")
    return errors


def record_remote_many_to_many_changes_and_save(request, obj, form, change, many_to_many_field, save_function_pointer):
    """
    TODO: This should be done through pre/post save
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
            # We can see the previous members of the object model by looking it up
            # in the database because the member list hasn't been committed yet.
            added_members = set(current_members) - set(original_members)
            removed_members = set(original_members) - set(current_members)

        else:  # a model object is being created (instead of changed) so we can assume all the members are new...
            added_members = form.cleaned_data[many_to_many_field]

    # A primary key for the object is required to make many-to-many field changes.
    # If the object is being changed then it has already been assigned a primary key.
    if not change:
        save_function_pointer(request, obj, form, change)
    obj.user_set.set(form.cleaned_data[many_to_many_field])
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


def record_local_many_to_many_changes(request, obj, form, many_to_many_field, form_field=None):
    """
    TODO: This should be done through pre/post save
    Record the changes in a many-to-many field that the model owns.
    """
    data_field = form_field or many_to_many_field
    if data_field in form.changed_data:
        original_members = set(getattr(obj, many_to_many_field).all())
        current_members = set(form.cleaned_data[data_field])
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
    TODO: this should be done in post_save rather than save_model
    """
    if field_name in form.changed_data or is_initial_creation:
        activity_entry = ActivityHistory()
        activity_entry.authorizer = request.user
        activity_entry.action = getattr(obj, field_name)
        activity_entry.content_object = obj
        activity_entry.save()
