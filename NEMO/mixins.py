from __future__ import annotations

import datetime
from datetime import timedelta
from typing import Dict, Optional, TYPE_CHECKING

from dateutil import rrule
from django.contrib.auth import get_permission_codename
from django.core.exceptions import NON_FIELD_ERRORS
from django.shortcuts import redirect
from django.utils import timezone

from NEMO.constants import NEXT_PARAMETER_NAME
from NEMO.utilities import RecurrenceFrequency, beginning_of_the_day, format_datetime, get_recurring_rule

if TYPE_CHECKING:
    from NEMO.models import Tool, User

DF = "SHORT_DATE_FORMAT"
DTF = "SHORT_DATETIME_FORMAT"


class CalendarDisplayMixin:
    """
    Inherit from this class to express that a class type can be displayed in the NEMO calendar.
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


class BillableItemMixin:
    """
    Mixin to be used for any billable item, currently only used by adjustment requests
    TODO: refactor billing api and other places to leverage this mixin
    """

    AREA_ACCESS = "area_access"
    TOOL_USAGE = "tool_usage"
    REMOTE_WORK = "remote_work"
    TRAINING = "training"
    CONSUMABLE = "consumable"
    MISSED_RESERVATION = "missed_reservation"

    def get_customer(self) -> User:
        if self.get_real_type() in [
            BillableItemMixin.AREA_ACCESS,
            BillableItemMixin.REMOTE_WORK,
            BillableItemMixin.CONSUMABLE,
        ]:
            return self.customer
        elif self.get_real_type() in [BillableItemMixin.TOOL_USAGE, BillableItemMixin.MISSED_RESERVATION]:
            return self.user
        elif self.get_real_type() == BillableItemMixin.TRAINING:
            return self.trainee

    def get_operator(self) -> Optional[User]:
        if self.get_real_type() == BillableItemMixin.AREA_ACCESS:
            return self.staff_charge.staff_member if self.staff_charge else None
        elif self.get_real_type() == BillableItemMixin.TOOL_USAGE:
            return self.operator
        elif self.get_real_type() == BillableItemMixin.REMOTE_WORK:
            return self.staff_member
        elif self.get_real_type() == BillableItemMixin.TRAINING:
            return self.trainer
        elif self.get_real_type() == BillableItemMixin.CONSUMABLE:
            return self.merchant
        elif self.get_real_type() == BillableItemMixin.MISSED_RESERVATION:
            return self.creator

    def get_item(self) -> str:
        if self.get_real_type() == BillableItemMixin.AREA_ACCESS:
            return f"{self.area} access"
        elif self.get_real_type() == BillableItemMixin.TOOL_USAGE:
            return f"{self.tool} usage"
        elif self.get_real_type() == BillableItemMixin.REMOTE_WORK:
            return "Staff time"
        elif self.get_real_type() == BillableItemMixin.TRAINING:
            return f"{self.get_type_display()} training"
        elif self.get_real_type() == BillableItemMixin.CONSUMABLE:
            quantity = f" (x {self.quantity})" if self.quantity > 1 else ""
            return f"{self.consumable}{quantity}"
        elif self.get_real_type() == BillableItemMixin.MISSED_RESERVATION:
            return f"{self.tool or self.area} missed reservation"

    def waive(self, user: User):
        if hasattr(self, "waived"):
            self.waived = True
            self.waived_by = user
            self.waived_on = timezone.now()
            self.save(update_fields=["waived", "waived_by", "waived_on"])

    def validate(self, user: User):
        if hasattr(self, "validated"):
            self.validated = True
            self.validated_by = user
            self.save(update_fields=["validated", "validated_by"])

    def get_start(self) -> Optional[datetime.datetime]:
        if self.get_real_type() in [
            BillableItemMixin.AREA_ACCESS,
            BillableItemMixin.TOOL_USAGE,
            BillableItemMixin.REMOTE_WORK,
            BillableItemMixin.MISSED_RESERVATION,
        ]:
            return self.start

    def get_end(self) -> Optional[datetime.datetime]:
        if self.get_real_type() in [
            BillableItemMixin.AREA_ACCESS,
            BillableItemMixin.TOOL_USAGE,
            BillableItemMixin.REMOTE_WORK,
            BillableItemMixin.MISSED_RESERVATION,
        ]:
            return self.end
        elif self.get_real_type() in [BillableItemMixin.TRAINING, BillableItemMixin.CONSUMABLE]:
            return self.date

    def can_be_adjusted(self, user: User):
        # determine if the given user can make an adjustment request for this charge
        from NEMO.views.customization import AdjustmentRequestsCustomization
        from NEMO.views.usage import get_managed_projects

        pi_projects = get_managed_projects(user)

        tool: Optional[Tool] = getattr(self, "tool", None)
        time_limit = AdjustmentRequestsCustomization.get_date_limit()
        time_limit_condition = not time_limit or time_limit <= self.get_end()
        user_project_condition = self.get_customer() == user or self.project in pi_projects
        operator_is_staff = self.get_operator() == user and user.is_staff_on_tool(tool)
        if self.get_real_type() == BillableItemMixin.AREA_ACCESS:
            access_enabled = AdjustmentRequestsCustomization.get_bool("adjustment_requests_area_access_enabled")
            remote_enabled = AdjustmentRequestsCustomization.get_bool("adjustment_requests_staff_staff_charges_enabled")
            if self.staff_charge:
                return remote_enabled and time_limit_condition and operator_is_staff
            else:
                return access_enabled and user_project_condition and time_limit_condition
        elif self.get_real_type() == BillableItemMixin.TOOL_USAGE:
            remote_enabled = AdjustmentRequestsCustomization.get_bool("adjustment_requests_staff_staff_charges_enabled")
            usage_enabled = AdjustmentRequestsCustomization.get_bool("adjustment_requests_tool_usage_enabled")
            if self.remote_work:
                return remote_enabled and time_limit_condition and operator_is_staff
            else:
                return (
                    usage_enabled
                    and time_limit_condition
                    and user_project_condition
                    and (self.get_customer() == self.get_operator() or not self.remote_work)
                ) or (
                    remote_enabled
                    and self.get_operator() == user
                    and user.is_staff_on_tool(tool)
                    and self.get_operator() != self.get_customer()
                )
        elif self.get_real_type() == BillableItemMixin.REMOTE_WORK:
            remote_enabled = AdjustmentRequestsCustomization.get_bool("adjustment_requests_staff_staff_charges_enabled")
            return remote_enabled and time_limit_condition and operator_is_staff
        elif self.get_real_type() == BillableItemMixin.TRAINING:
            return False
        elif self.get_real_type() == BillableItemMixin.CONSUMABLE:
            withdrawal_enabled = AdjustmentRequestsCustomization.get_bool(
                "adjustment_requests_consumable_withdrawal_enabled"
            )
            self_check = AdjustmentRequestsCustomization.get_bool(
                "adjustment_requests_consumable_withdrawal_self_checkout"
            )
            staff_check = AdjustmentRequestsCustomization.get_bool(
                "adjustment_requests_consumable_withdrawal_staff_checkout"
            )
            usage_event = AdjustmentRequestsCustomization.get_bool(
                "adjustment_requests_consumable_withdrawal_usage_event"
            )
            type_condition = True
            if not self_check:
                consumable_self_checked = (
                    self.consumable.allow_self_checkout
                    and self.get_operator() == self.get_customer()
                    and not self.usage_event
                )
                type_condition = type_condition and not consumable_self_checked
            if not staff_check:
                consumable_staff_check = (
                    not self.usage_event and self.get_operator().is_staff and self.get_operator() != self.get_customer()
                )
                type_condition = type_condition and not consumable_staff_check
            if not usage_event:
                type_condition = type_condition and not self.usage_event
            return withdrawal_enabled and time_limit_condition and type_condition and user_project_condition
        elif self.get_real_type() == BillableItemMixin.MISSED_RESERVATION:
            missed_res_enabled = AdjustmentRequestsCustomization.get_bool(
                "adjustment_requests_missed_reservation_enabled"
            )
            return missed_res_enabled and time_limit_condition and user_project_condition

    def can_be_waived(self):
        from NEMO.views.customization import AdjustmentRequestsCustomization
        from NEMO.models import AreaAccessRecord, ConsumableWithdraw, Reservation, UsageEvent

        return (
            isinstance(self, AreaAccessRecord)
            and AdjustmentRequestsCustomization.get_bool("adjustment_requests_waive_area_access_enabled")
            or isinstance(self, UsageEvent)
            and AdjustmentRequestsCustomization.get_bool("adjustment_requests_waive_tool_usage_enabled")
            or isinstance(self, ConsumableWithdraw)
            and AdjustmentRequestsCustomization.get_bool("adjustment_requests_waive_consumable_withdrawal_enabled")
            or isinstance(self, Reservation)
            and AdjustmentRequestsCustomization.get_bool("adjustment_requests_waive_missed_reservation_enabled")
        )

    def can_times_be_changed(item):
        from NEMO.views.customization import AdjustmentRequestsCustomization
        from NEMO.models import ConsumableWithdraw, Reservation

        can_change_reservation_times = AdjustmentRequestsCustomization.get_bool(
            "adjustment_requests_missed_reservation_times"
        )
        return (
            item
            and not isinstance(item, ConsumableWithdraw)
            and (not isinstance(item, Reservation) or can_change_reservation_times)
        )

    def can_quantity_be_changed(self):
        from NEMO.models import ConsumableWithdraw

        return isinstance(self, ConsumableWithdraw)

    def get_operator_action(self) -> str:
        if self.get_real_type() == BillableItemMixin.AREA_ACCESS:
            return "entered "
        elif self.get_real_type() == BillableItemMixin.TOOL_USAGE:
            return "performed "
        elif self.get_real_type() == BillableItemMixin.REMOTE_WORK:
            return ""
        elif self.get_real_type() == BillableItemMixin.TRAINING:
            return "trained "
        elif self.get_real_type() == BillableItemMixin.CONSUMABLE:
            return "charged "
        elif self.get_real_type() == BillableItemMixin.MISSED_RESERVATION:
            return "created "

    def get_real_type(self) -> str:
        from NEMO.models import (
            AreaAccessRecord,
            UsageEvent,
            StaffCharge,
            TrainingSession,
            ConsumableWithdraw,
            Reservation,
        )

        if isinstance(self, AreaAccessRecord):
            return BillableItemMixin.AREA_ACCESS
        elif isinstance(self, UsageEvent):
            return BillableItemMixin.TOOL_USAGE
        elif isinstance(self, StaffCharge):
            return BillableItemMixin.REMOTE_WORK
        elif isinstance(self, TrainingSession):
            return BillableItemMixin.TRAINING
        elif isinstance(self, ConsumableWithdraw):
            return BillableItemMixin.CONSUMABLE
        elif isinstance(self, Reservation):
            return BillableItemMixin.MISSED_RESERVATION

    def get_billable_type(self) -> str:
        from NEMO.models import AreaAccessRecord, UsageEvent

        if isinstance(self, AreaAccessRecord):
            if self.staff_charge:
                return BillableItemMixin.REMOTE_WORK
            return BillableItemMixin.AREA_ACCESS
        elif isinstance(self, UsageEvent):
            if self.remote_work:
                return BillableItemMixin.REMOTE_WORK
            return BillableItemMixin.TOOL_USAGE
        else:
            return self.get_real_type()

    def get_display(self, user: User = None) -> str:
        customer_display = f" for {self.get_customer()}"
        operator_display = f" {self.get_operator_action()}by {self.get_operator()}"
        user_display = ""
        if not user or user != self.get_customer():
            user_display += customer_display
        if self.get_operator() and self.get_customer() != self.get_operator():
            if not user or user != self.get_operator():
                user_display += operator_display
        charge_time = ""
        if self.get_start() and self.get_end():
            charge_time = f" from {format_datetime(self.get_start(), DTF)} to {format_datetime(self.get_end(), DTF)}"
        elif self.get_start() or self.get_end():
            charge_time = f" on {format_datetime(self.get_start() or self.get_end(), DTF)}"
        return f"{self.get_item()}{user_display}{charge_time}"


class RecurrenceMixin:
    @property
    def get_rec_frequency_enum(self):
        return RecurrenceFrequency(self.rec_frequency)

    def get_recurrence(self) -> rrule:
        if self.rec_start and self.rec_frequency:
            return get_recurring_rule(
                self.rec_start, self.get_rec_frequency_enum, self.rec_until, self.rec_interval, self.rec_count
            )

    def next_recurrence(self, inc=False) -> datetime:
        today = beginning_of_the_day(datetime.datetime.now(), in_local_timezone=False)
        recurrence = self.get_recurrence()
        return recurrence.after(today, inc=inc) if recurrence else None

    def get_recurrence_interval_display(self) -> str:
        if not self.rec_start or not self.rec_frequency:
            return ""
        interval = f"{self.rec_interval} " if self.rec_interval != 1 else ""
        f_enum = self.get_rec_frequency_enum
        frequency = f"{f_enum.display_text}s" if self.rec_interval != 1 else f_enum.display_text
        return f"Every {interval}{frequency}"

    def get_recurrence_display(self) -> str:
        rec_display = ""
        if self.rec_start and self.rec_frequency:
            start = f", starting {format_datetime(self.rec_start, 'SHORT_DATE_FORMAT')}"
            end = ""
            if self.rec_until or self.rec_count:
                end = f" and ending "
                if self.rec_until:
                    end += f"on {format_datetime(self.rec_until, 'SHORT_DATE_FORMAT')}"
                elif self.rec_count:
                    end += f"after {self.rec_count} iterations" if self.rec_count != 1 else f"after one time"
                    if self.get_recurrence():
                        end += f" on {format_datetime(list(self.get_recurrence())[-1], 'SHORT_DATE_FORMAT')}"
            return f"{self.get_recurrence_interval_display()}{start}{end}"
        return rec_display

    def clean_recurrence(self) -> Dict:
        errors = {}
        if not self.rec_start:
            errors["rec_start"] = "This field is required."
        if not self.rec_frequency:
            errors["rec_frequency"] = "This field is required."
        if self.rec_until and self.rec_count:
            errors[NON_FIELD_ERRORS] = "'count' and 'until' cannot be used at the same time."
        return errors


# Admin mixin to allow redirect after add or change
class ModelAdminRedirectMixin:
    def response_post_save_add(self, request, obj):
        return self.response_redirect(request, super().response_post_save_add(request, obj))

    def response_post_save_change(self, request, obj):
        return self.response_redirect(request, super().response_post_save_change(request, obj))

    def response_delete(self, request, obj_display, obj_id):
        return self.response_redirect(request, super().response_delete(request, obj_display, obj_id))

    def response_redirect(self, request, original_response):
        if NEXT_PARAMETER_NAME in request.GET:
            return redirect(request.GET[NEXT_PARAMETER_NAME])
        return original_response


# Mixin to use the obj in permissions. By default, admin classes ignore the actual obj
class ObjPermissionAdminMixin:
    def has_change_permission(self, request, obj=None):
        """
        Return True if the given request has permission to change the given
        Django model instance, the default implementation doesn't examine the
        `obj` parameter.

        Can be overridden by the user in subclasses. In such case it should
        return True if the given request has permission to change the `obj`
        model instance. If `obj` is None, this should return True if the given
        request has permission to change *any* object of the given type.
        """
        opts = self.opts
        codename = get_permission_codename("change", opts)
        return request.user.has_perm("%s.%s" % (opts.app_label, codename), obj)

    def has_delete_permission(self, request, obj=None):
        """
        Return True if the given request has permission to change the given
        Django model instance, the default implementation doesn't examine the
        `obj` parameter.

        Can be overridden by the user in subclasses. In such case it should
        return True if the given request has permission to delete the `obj`
        model instance. If `obj` is None, this should return True if the given
        request has permission to delete *any* object of the given type.
        """
        opts = self.opts
        codename = get_permission_codename("delete", opts)
        return request.user.has_perm("%s.%s" % (opts.app_label, codename), obj)

    def has_view_permission(self, request, obj=None):
        """
        Return True if the given request has permission to view the given
        Django model instance. The default implementation doesn't examine the
        `obj` parameter.

        If overridden by the user in subclasses, it should return True if the
        given request has permission to view the `obj` model instance. If `obj`
        is None, it should return True if the request has permission to view
        any object of the given type.
        """
        opts = self.opts
        codename_view = get_permission_codename("view", opts)
        codename_change = get_permission_codename("change", opts)
        return request.user.has_perm("%s.%s" % (opts.app_label, codename_view), obj) or request.user.has_perm(
            "%s.%s" % (opts.app_label, codename_change), obj
        )


class ConfigurationMixin:
    def calendar_colors_as_list(self):
        return [x.strip() for x in self.calendar_colors.split(",")] if self.calendar_colors else []

    def get_available_setting(self, choice):
        choice = int(choice)
        available_settings = self.available_settings_as_list()
        return available_settings[choice]

    def current_settings_as_list(self):
        return [x.strip() for x in self.current_settings.split(",")]

    def available_settings_as_list(self):
        return [x.strip() for x in self.available_settings.split(",")] if self.available_settings else []
