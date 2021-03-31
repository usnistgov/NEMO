from datetime import datetime, timedelta
from decimal import Decimal
from typing import List, Optional

from django import forms
from django.db.models import QuerySet
from django.utils import timezone

from NEMO.models import Project, User, UsageEvent, AreaAccessRecord, ConsumableWithdraw, Reservation, StaffCharge, TrainingSession
from NEMO.utilities import localize

date_time_format = '%m/%d/%Y %H:%M:%S'


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
		return localize(datetime.combine(self.cleaned_data['start'], datetime.min.time()))

	def get_end_date(self):
		return localize(datetime.combine(self.cleaned_data['end'], datetime.max.time()))

	def get_project_id(self):
		return self.cleaned_data['project_id']

	def get_project_name(self):
		return self.cleaned_data['project_name']

	def get_account_id(self):
		return self.cleaned_data['account_id']

	def get_account_name(self):
		return self.cleaned_data['account_name']

	def get_username(self):
		return self.cleaned_data['username']

	def get_application_name(self):
		return self.cleaned_data['application_name']


class BillableItem(object):
	def __init__(self, item_type: str, project: Project, user: User):
		self.type: Optional[str] = item_type
		self.name: Optional[str] = None
		self.details: Optional[str] = ''
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


def get_usage_events_for_billing(billing_form: BillingFilterForm) -> List[BillableItem]:
	queryset = UsageEvent.objects.filter()
	start, end = billing_form.get_start_date(), billing_form.get_end_date()
	queryset = queryset.filter(start__gte=start, end__lte=end, start__lte=end, end__gte=start)
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
	queryset = AreaAccessRecord.objects.filter()
	start, end = billing_form.get_start_date(), billing_form.get_end_date()
	queryset = queryset.filter(start__gte=start, end__lte=end, start__lte=end, end__gte=start)
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
	queryset = Reservation.objects.filter(missed=True)
	start, end = billing_form.get_start_date(), billing_form.get_end_date()
	queryset = queryset.filter(start__gte=start, end__lte=end, start__lte=end, end__gte=start)
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
	queryset = StaffCharge.objects.filter()
	start, end = billing_form.get_start_date(), billing_form.get_end_date()
	queryset = queryset.filter(start__gte=start, end__lte=end, start__lte=end, end__gte=start)
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
	queryset = ConsumableWithdraw.objects.filter()
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
	queryset = TrainingSession.objects.filter()
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


def billable_items_usage_events(usage_events: QuerySet) -> List[BillableItem]:
	billable_items: List[BillableItem] = []
	usage_event: UsageEvent
	for usage_event in usage_events:
		item = BillableItem('tool_usage', usage_event.project, usage_event.user)
		item.name = usage_event.tool.name
		item.details = f"Work performed by {usage_event.operator} on user's behalf" if usage_event.operator != usage_event.user else ''
		item.start = usage_event.start.astimezone(timezone.get_current_timezone()).strftime(date_time_format)
		item.end = usage_event.end.astimezone(timezone.get_current_timezone()).strftime(date_time_format)
		item.quantity = get_minutes_between_dates(usage_event.start, usage_event.end)
		billable_items.append(item)
	return billable_items


def billable_items_area_access_records(area_access_records: QuerySet) -> List[BillableItem]:
	billable_items: List[BillableItem] = []
	area_access_record: AreaAccessRecord
	for area_access_record in area_access_records:
		item = BillableItem('area_access', area_access_record.project, area_access_record.customer)
		item.name = area_access_record.area.name
		item.details = f"Area accessed by {area_access_record.staff_charge.staff_member} on user's behalf" if area_access_record.staff_charge else ''
		item.start = area_access_record.start.astimezone(timezone.get_current_timezone()).strftime(date_time_format)
		item.end = area_access_record.end.astimezone(timezone.get_current_timezone()).strftime(date_time_format)
		item.quantity = get_minutes_between_dates(area_access_record.start, area_access_record.end)
		billable_items.append(item)
	return billable_items


def billable_items_consumable_withdrawals(withdrawals: QuerySet) -> List[BillableItem]:
	billable_items: List[BillableItem] = []
	consumable_withdrawal: ConsumableWithdraw
	for consumable_withdrawal in withdrawals:
		item = BillableItem('consumable', consumable_withdrawal.project, consumable_withdrawal.customer)
		item.name = consumable_withdrawal.consumable.name
		item.start = consumable_withdrawal.date.astimezone(timezone.get_current_timezone()).strftime(date_time_format)
		item.end = consumable_withdrawal.date.astimezone(timezone.get_current_timezone()).strftime(date_time_format)
		item.quantity = consumable_withdrawal.quantity
		billable_items.append(item)
	return billable_items


def billable_items_missed_reservations(missed_reservations: QuerySet) -> List[BillableItem]:
	billable_items: List[BillableItem] = []
	missed_reservation: Reservation
	for missed_reservation in missed_reservations:
		item = BillableItem('missed_reservation', missed_reservation.project, missed_reservation.user)
		item.name = missed_reservation.reservation_item.name
		item.start = missed_reservation.start.astimezone(timezone.get_current_timezone()).strftime(date_time_format)
		item.end = missed_reservation.end.astimezone(timezone.get_current_timezone()).strftime(date_time_format)
		item.quantity = 1
		billable_items.append(item)
	return billable_items


def billable_items_staff_charges(staff_charges: QuerySet) -> List[BillableItem]:
	billable_items: List[BillableItem] = []
	staff_charge: StaffCharge
	for staff_charge in staff_charges:
		item = BillableItem('staff_charge', staff_charge.project, staff_charge.customer)
		item.name = f'Work performed by {staff_charge.staff_member}'
		item.start = staff_charge.start.astimezone(timezone.get_current_timezone()).strftime(date_time_format)
		item.end = staff_charge.end.astimezone(timezone.get_current_timezone()).strftime(date_time_format)
		item.quantity = get_minutes_between_dates(staff_charge.start, staff_charge.end)
		billable_items.append(item)
	return billable_items


def billable_items_training_sessions(training_sessions: QuerySet) -> List[BillableItem]:
	billable_items: List[BillableItem] = []
	training_session: TrainingSession
	for training_session in training_sessions:
		item = BillableItem('training_session', training_session.project, training_session.trainee)
		item.name = training_session.tool.name
		item.details = f'{training_session.get_type_display()} training provided by {training_session.trainer}'
		item.start = training_session.date.astimezone(timezone.get_current_timezone()).strftime(date_time_format)
		item.end = training_session.date.astimezone(timezone.get_current_timezone()).strftime(date_time_format)
		item.quantity = training_session.duration
		billable_items.append(item)
	return billable_items


def get_minutes_between_dates(start, end, round_digits=2) -> Decimal:
	diff: timedelta = end - start
	return round(Decimal(diff.total_seconds()) / Decimal(60), round_digits)
