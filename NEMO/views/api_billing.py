from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional

from django import forms
from django.contrib.contenttypes.models import ContentType

from NEMO.models import (
    AreaAccessRecord,
    ConsumableWithdraw,
    Project,
    Reservation,
    StaffCharge,
    TrainingSession,
    UsageEvent,
    User,
)
from NEMO.typing import QuerySetType
from NEMO.utilities import localize


class BillingFilterForm(forms.Form):
    start = forms.DateField(required=True)
    end = forms.DateField(required=True)
    username = forms.CharField(required=False)
    account_name = forms.CharField(required=False)
    account_id = forms.IntegerField(required=False)
    application_name = forms.CharField(required=False)
    project_name = forms.CharField(required=False)
    project_id = forms.IntegerField(required=False)

    def get_start_date(self):
        return localize(datetime.combine(self.cleaned_data["start"], datetime.min.time()))

    def get_end_date(self):
        return localize(datetime.combine(self.cleaned_data["end"], datetime.max.time()))

    def get_project_id(self):
        return self.cleaned_data["project_id"]

    def get_project_name(self):
        return self.cleaned_data["project_name"]

    def get_account_id(self):
        return self.cleaned_data["account_id"]

    def get_account_name(self):
        return self.cleaned_data["account_name"]

    def get_username(self):
        return self.cleaned_data["username"]

    def get_application_name(self):
        return self.cleaned_data["application_name"]


class BillableItem(object):
    def __init__(self, item_type: str, project: Project, user: User, item=None):
        self.item = item
        self.type: Optional[str] = item_type
        self.name: Optional[str] = None
        self.details: Optional[str] = ""
        self.item_id: Optional[int] = item.id if item else None
        self.item_content_type_id: Optional[int] = (
            ContentType.objects.get_for_model(item, for_concrete_model=False).id if item else None
        )
        self.validated: bool = False
        self.validated_by: Optional[User] = None
        self.waived: bool = False
        self.waived_by: Optional[User] = None
        self.waived_on: Optional[datetime] = None
        if project:
            self.account: Optional[str] = project.account.name
            self.account_id: Optional[int] = project.account.id
            self.project: Optional[str] = project.name
            self.project_id: Optional[int] = project.id
            self.application: Optional[str] = project.application_identifier
        if user:
            self.user: Optional[str] = str(user)
            self.username: Optional[str] = user.username
            self.user_id: Optional[int] = user.id
        self.start: Optional[datetime] = None
        self.end: Optional[datetime] = None
        self.quantity: Optional[Decimal] = None


def get_billing_charges(request_params: Dict) -> List[BillableItem]:
    billing_form = BillingFilterForm(request_params)
    billing_form.full_clean()
    data: List[BillableItem] = []
    data.extend(get_usage_events_for_billing(billing_form))
    data.extend(get_area_access_for_billing(billing_form))
    data.extend(get_consumables_for_billing(billing_form))
    data.extend(get_missed_reservations_for_billing(billing_form))
    data.extend(get_staff_charges_for_billing(billing_form))
    data.extend(get_training_sessions_for_billing(billing_form))

    data.sort(key=lambda x: x.start, reverse=True)
    return data


def get_usage_events_for_billing(billing_form: BillingFilterForm) -> List[BillableItem]:
    queryset = UsageEvent.objects.filter().prefetch_related("project", "project__account", "user", "operator", "tool")
    start, end = billing_form.get_start_date(), billing_form.get_end_date()
    queryset = queryset.filter(end__gte=start, end__lte=end)
    if billing_form.get_account_id():
        queryset = queryset.filter(project__account_id=billing_form.get_account_id())
    if billing_form.get_account_name():
        queryset = queryset.filter(project__account__name=billing_form.get_account_name())
    if billing_form.get_project_id():
        queryset = queryset.filter(project__id=billing_form.get_project_id())
    if billing_form.get_project_name():
        queryset = queryset.filter(project__name=billing_form.get_project_name())
    if billing_form.get_application_name():
        queryset = queryset.filter(project__application_identifier=billing_form.get_application_name())
    if billing_form.get_username():
        queryset = queryset.filter(user__username=billing_form.get_username())
    return billable_items_usage_events(queryset)


def get_area_access_for_billing(billing_form: BillingFilterForm) -> List[BillableItem]:
    queryset = AreaAccessRecord.objects.filter().prefetch_related("project", "project__account", "customer", "area")
    start, end = billing_form.get_start_date(), billing_form.get_end_date()
    queryset = queryset.filter(end__gte=start, end__lte=end)
    if billing_form.get_account_id():
        queryset = queryset.filter(project__account_id=billing_form.get_account_id())
    if billing_form.get_account_name():
        queryset = queryset.filter(project__account__name=billing_form.get_account_name())
    if billing_form.get_project_id():
        queryset = queryset.filter(project__id=billing_form.get_project_id())
    if billing_form.get_project_name():
        queryset = queryset.filter(project__name=billing_form.get_project_name())
    if billing_form.get_application_name():
        queryset = queryset.filter(project__application_identifier=billing_form.get_application_name())
    if billing_form.get_username():
        queryset = queryset.filter(customer__username=billing_form.get_username())
    return billable_items_area_access_records(queryset)


def get_missed_reservations_for_billing(billing_form: BillingFilterForm) -> List[BillableItem]:
    queryset = Reservation.objects.filter(missed=True).prefetch_related(
        "project", "project__account", "user", "area", "tool"
    )
    start, end = billing_form.get_start_date(), billing_form.get_end_date()
    queryset = queryset.filter(end__gte=start, end__lte=end)
    if billing_form.get_account_id():
        queryset = queryset.filter(project__account_id=billing_form.get_account_id())
    if billing_form.get_account_name():
        queryset = queryset.filter(project__account__name=billing_form.get_account_name())
    if billing_form.get_project_id():
        queryset = queryset.filter(project__id=billing_form.get_project_id())
    if billing_form.get_project_name():
        queryset = queryset.filter(project__name=billing_form.get_project_name())
    if billing_form.get_application_name():
        queryset = queryset.filter(project__application_identifier=billing_form.get_application_name())
    if billing_form.get_username():
        queryset = queryset.filter(user__username=billing_form.get_username())
    return billable_items_missed_reservations(queryset)


def get_staff_charges_for_billing(billing_form: BillingFilterForm) -> List[BillableItem]:
    queryset = StaffCharge.objects.filter().prefetch_related("project", "project__account", "customer", "staff_member")
    start, end = billing_form.get_start_date(), billing_form.get_end_date()
    queryset = queryset.filter(end__gte=start, end__lte=end)
    if billing_form.get_account_id():
        queryset = queryset.filter(project__account_id=billing_form.get_account_id())
    if billing_form.get_account_name():
        queryset = queryset.filter(project__account__name=billing_form.get_account_name())
    if billing_form.get_project_id():
        queryset = queryset.filter(project__id=billing_form.get_project_id())
    if billing_form.get_project_name():
        queryset = queryset.filter(project__name=billing_form.get_project_name())
    if billing_form.get_application_name():
        queryset = queryset.filter(project__application_identifier=billing_form.get_application_name())
    if billing_form.get_username():
        queryset = queryset.filter(customer__username=billing_form.get_username())
    return billable_items_staff_charges(queryset)


def get_consumables_for_billing(billing_form: BillingFilterForm) -> List[BillableItem]:
    queryset = ConsumableWithdraw.objects.filter().prefetch_related(
        "project", "project__account", "customer", "merchant", "consumable"
    )
    start, end = billing_form.get_start_date(), billing_form.get_end_date()
    queryset = queryset.filter(date__gte=start, date__lte=end)
    if billing_form.get_account_id():
        queryset = queryset.filter(project__account_id=billing_form.get_account_id())
    if billing_form.get_account_name():
        queryset = queryset.filter(project__account__name=billing_form.get_account_name())
    if billing_form.get_project_id():
        queryset = queryset.filter(project__id=billing_form.get_project_id())
    if billing_form.get_project_name():
        queryset = queryset.filter(project__name=billing_form.get_project_name())
    if billing_form.get_application_name():
        queryset = queryset.filter(project__application_identifier=billing_form.get_application_name())
    if billing_form.get_username():
        queryset = queryset.filter(customer__username=billing_form.get_username())
    return billable_items_consumable_withdrawals(queryset)


def get_training_sessions_for_billing(billing_form: BillingFilterForm) -> List[BillableItem]:
    queryset = TrainingSession.objects.filter().prefetch_related(
        "project", "project__account", "trainer", "trainee", "tool"
    )
    start, end = billing_form.get_start_date(), billing_form.get_end_date()
    queryset = queryset.filter(date__gte=start, date__lte=end)
    if billing_form.get_account_id():
        queryset = queryset.filter(project__account_id=billing_form.get_account_id())
    if billing_form.get_account_name():
        queryset = queryset.filter(project__account__name=billing_form.get_account_name())
    if billing_form.get_project_id():
        queryset = queryset.filter(project__id=billing_form.get_project_id())
    if billing_form.get_project_name():
        queryset = queryset.filter(project__name=billing_form.get_project_name())
    if billing_form.get_application_name():
        queryset = queryset.filter(project__application_identifier=billing_form.get_application_name())
    if billing_form.get_username():
        queryset = queryset.filter(trainee__username=billing_form.get_username())
    return billable_items_training_sessions(queryset)


def billable_items_usage_events(usage_events: QuerySetType[UsageEvent]) -> List[BillableItem]:
    billable_items: List[BillableItem] = []
    for usage_event in usage_events:
        item = BillableItem("tool_usage", usage_event.project, usage_event.user, usage_event)
        item.name = usage_event.tool.name
        item.details = (
            f"Work performed by {usage_event.operator} on user's behalf"
            if usage_event.operator != usage_event.user
            else ""
        )
        item.start = usage_event.start
        item.end = usage_event.end
        item.quantity = get_minutes_between_dates(usage_event.start, usage_event.end)
        item.validated = usage_event.validated
        item.validated_by = usage_event.validated_by
        item.waived = usage_event.waived
        item.waived_on = usage_event.waived_on
        item.waived_by = usage_event.waived_by
        billable_items.append(item)
    return billable_items


def billable_items_area_access_records(area_access_records: QuerySetType[AreaAccessRecord]) -> List[BillableItem]:
    billable_items: List[BillableItem] = []
    for area_access_record in area_access_records:
        item = BillableItem("area_access", area_access_record.project, area_access_record.customer, area_access_record)
        item.name = area_access_record.area.name
        item.details = (
            f"Area accessed by {area_access_record.staff_charge.staff_member} on user's behalf"
            if area_access_record.staff_charge
            else ""
        )
        item.start = area_access_record.start
        item.end = area_access_record.end
        item.quantity = get_minutes_between_dates(area_access_record.start, area_access_record.end)
        item.validated = area_access_record.validated
        item.validated_by = area_access_record.validated_by
        item.waived = area_access_record.waived
        item.waived_on = area_access_record.waived_on
        item.waived_by = area_access_record.waived_by
        billable_items.append(item)
    return billable_items


def billable_items_consumable_withdrawals(withdrawals: QuerySetType[ConsumableWithdraw]) -> List[BillableItem]:
    billable_items: List[BillableItem] = []
    for consumable_withdrawal in withdrawals:
        item = BillableItem(
            "consumable", consumable_withdrawal.project, consumable_withdrawal.customer, consumable_withdrawal
        )
        item.name = consumable_withdrawal.consumable.name
        item.start = consumable_withdrawal.date
        item.end = consumable_withdrawal.date
        item.quantity = consumable_withdrawal.quantity
        item.validated = consumable_withdrawal.validated
        item.validated_by = consumable_withdrawal.validated_by
        item.waived = consumable_withdrawal.waived
        item.waived_on = consumable_withdrawal.waived_on
        item.waived_by = consumable_withdrawal.waived_by
        billable_items.append(item)
    return billable_items


def billable_items_missed_reservations(missed_reservations: QuerySetType[Reservation]) -> List[BillableItem]:
    billable_items: List[BillableItem] = []
    for missed_reservation in missed_reservations:
        item = BillableItem(
            "missed_reservation", missed_reservation.project, missed_reservation.user, missed_reservation
        )
        item.name = missed_reservation.reservation_item.name
        item.start = missed_reservation.start
        item.end = missed_reservation.end
        item.quantity = 1
        item.validated = missed_reservation.validated
        item.validated_by = missed_reservation.validated_by
        item.waived = missed_reservation.waived
        item.waived_on = missed_reservation.waived_on
        item.waived_by = missed_reservation.waived_by
        billable_items.append(item)
    return billable_items


def billable_items_staff_charges(staff_charges: QuerySetType[StaffCharge]) -> List[BillableItem]:
    billable_items: List[BillableItem] = []
    for staff_charge in staff_charges:
        item = BillableItem("staff_charge", staff_charge.project, staff_charge.customer, staff_charge)
        item.details = staff_charge.note
        item.name = f"Work performed by {staff_charge.staff_member}"
        item.start = staff_charge.start
        item.end = staff_charge.end
        item.quantity = get_minutes_between_dates(staff_charge.start, staff_charge.end)
        item.validated = staff_charge.validated
        item.validated_by = staff_charge.validated_by
        item.waived = staff_charge.waived
        item.waived_on = staff_charge.waived_on
        item.waived_by = staff_charge.waived_by
        billable_items.append(item)
    return billable_items


def billable_items_training_sessions(training_sessions: QuerySetType[TrainingSession]) -> List[BillableItem]:
    billable_items: List[BillableItem] = []
    for training_session in training_sessions:
        item = BillableItem("training_session", training_session.project, training_session.trainee, training_session)
        item.name = training_session.tool.name
        item.details = f"{training_session.get_type_display()} training provided by {training_session.trainer}"
        item.start = training_session.date
        item.end = training_session.date
        item.quantity = training_session.duration
        item.validated = training_session.validated
        item.validated_by = training_session.validated_by
        item.waived = training_session.waived
        item.waived_on = training_session.waived_on
        item.waived_by = training_session.waived_by
        billable_items.append(item)
    return billable_items


def get_minutes_between_dates(start, end, round_digits=2) -> Decimal:
    diff: timedelta = end - start
    return round(Decimal(diff.total_seconds()) / Decimal(60), round_digits)
