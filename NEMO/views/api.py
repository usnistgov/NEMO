from datetime import datetime
from typing import List, Dict

from django import forms
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.viewsets import ReadOnlyModelViewSet

from NEMO.filters import ReservationFilter, UsageEventFilter, AreaAccessRecordFilter, UserFilter
from NEMO.models import User, Project, Account, Reservation, UsageEvent, AreaAccessRecord, Task, ScheduledOutage, Tool, \
	ConsumableWithdraw, TrainingSession, StaffCharge
from NEMO.serializers import UserSerializer, ProjectSerializer, AccountSerializer, ReservationSerializer, \
	UsageEventSerializer, AreaAccessRecordSerializer, TaskSerializer, ScheduledOutageSerializer, ToolSerializer, \
	BillableItemSerializer
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


class UserViewSet(ReadOnlyModelViewSet):
	queryset = User.objects.all()
	serializer_class = UserSerializer
	filter_class = UserFilter


class ProjectViewSet(ReadOnlyModelViewSet):
	queryset = Project.objects.all()
	serializer_class = ProjectSerializer


class AccountViewSet(ReadOnlyModelViewSet):
	queryset = Account.objects.all()
	serializer_class = AccountSerializer


class ToolViewSet(ReadOnlyModelViewSet):
	queryset = Tool.objects.all()
	serializer_class = ToolSerializer


class ReservationViewSet(ReadOnlyModelViewSet):
	queryset = Reservation.objects.all()
	serializer_class = ReservationSerializer
	filter_class = ReservationFilter


class UsageEventViewSet(ReadOnlyModelViewSet):
	queryset = UsageEvent.objects.all()
	serializer_class = UsageEventSerializer
	filter_class = UsageEventFilter


class AreaAccessRecordViewSet(ReadOnlyModelViewSet):
	queryset = AreaAccessRecord.objects.all()
	serializer_class = AreaAccessRecordSerializer
	filter_class = AreaAccessRecordFilter


class TaskViewSet(ReadOnlyModelViewSet):
	queryset = Task.objects.all()
	serializer_class = TaskSerializer


class ScheduledOutageViewSet(ReadOnlyModelViewSet):
	queryset = ScheduledOutage.objects.all()
	serializer_class = ScheduledOutageSerializer


@api_view(["GET"])
def billing(request):
	form = BillingFilterForm(request.GET)
	if not form.is_valid():
		return Response(status=status.HTTP_400_BAD_REQUEST, data=form.errors)

	data :List[Dict] = []
	usage_events = get_usage_events_for_billing(form)
	area_access = get_area_access_for_billing(form)
	consumables = get_consumables_for_billing(form)
	missed_reservation = get_missed_reservations_for_billing(form)
	staff_charges = get_staff_charges_for_billing(form)
	training_sessions = get_training_sessions_for_billing(form)

	data.extend(usage_events)
	data.extend(area_access)
	data.extend(consumables)
	data.extend(staff_charges)
	data.extend(missed_reservation)
	data.extend(training_sessions)

	serializer = BillableItemSerializer(data, many=True)
	return Response(serializer.data)


def get_usage_events_for_billing(billing_form: BillingFilterForm) -> List[Dict]:
	result = []
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
	usage_event: UsageEvent
	for usage_event in queryset:
		diff = usage_event.end - usage_event.start
		result.append({
			'type': 'tool_usage',
			'name': usage_event.tool.name,
			'details': f'Work performed by {usage_event.operator} on your behalf' if usage_event.operator != usage_event.user else '',
			'account': usage_event.project.account.name,
			'account_id': usage_event.project.account_id,
			'project': usage_event.project.name,
			'project_id': usage_event.project_id,
			'application': usage_event.project.application_identifier,
			'username': usage_event.user.username,
			'user_id': usage_event.user_id,
			'start': usage_event.start.astimezone(timezone.get_current_timezone()).strftime(date_time_format),
			'end': usage_event.end.astimezone(timezone.get_current_timezone()).strftime(date_time_format),
			'quantity': str(round(diff.days*1440 + diff.seconds/60, 2))
		})
	return result

def get_area_access_for_billing(billing_form: BillingFilterForm) -> List[Dict]:
	result = []
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
	area_access_record: AreaAccessRecord
	for area_access_record in queryset:
		diff = area_access_record.end - area_access_record.start
		result.append({
			'type': 'area_access',
			'name': area_access_record.area.name,
			'details': f'Area accessed by {area_access_record.staff_charge.staff_member} on your behalf' if area_access_record.staff_charge else '',
			'account': area_access_record.project.account.name,
			'account_id': area_access_record.project.account_id,
			'project': area_access_record.project.name,
			'project_id': area_access_record.project_id,
			'application': area_access_record.project.application_identifier,
			'username': area_access_record.customer.username,
			'user_id': area_access_record.customer_id,
			'start': area_access_record.start.astimezone(timezone.get_current_timezone()).strftime(date_time_format),
			'end': area_access_record.end.astimezone(timezone.get_current_timezone()).strftime(date_time_format),
			'quantity': str(round(diff.days*1440 + diff.seconds/60, 2))
		})
	return result


def get_missed_reservations_for_billing(billing_form: BillingFilterForm) -> List[Dict]:
	result = []
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
	missed_reservation: Reservation
	for missed_reservation in queryset:
		result.append({
			'type': 'missed_reservation',
			'name': missed_reservation.tool.name,
			'details': '',
			'account': missed_reservation.project.account.name,
			'account_id': missed_reservation.project.account_id,
			'project': missed_reservation.project.name,
			'project_id': missed_reservation.project_id,
			'application': missed_reservation.project.application_identifier,
			'username': missed_reservation.user.username,
			'user_id': missed_reservation.user_id,
			'start': missed_reservation.start.astimezone(timezone.get_current_timezone()).strftime(date_time_format),
			'end': missed_reservation.end.astimezone(timezone.get_current_timezone()).strftime(date_time_format),
			'quantity': 1
		})
	return result


def get_staff_charges_for_billing(billing_form: BillingFilterForm) -> List[Dict]:
	result = []
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
	staff_charge: StaffCharge
	for staff_charge in queryset:
		diff = staff_charge.end - staff_charge.start
		result.append({
			'type': 'staff_charge',
			'name': f'Work performed by {staff_charge.staff_member}',
			'details': '',
			'account': staff_charge.project.account.name,
			'account_id': staff_charge.project.account_id,
			'project': staff_charge.project.name,
			'project_id': staff_charge.project_id,
			'application': staff_charge.project.application_identifier,
			'username': staff_charge.customer.username,
			'user_id': staff_charge.customer_id,
			'start': staff_charge.start.astimezone(timezone.get_current_timezone()).strftime(date_time_format),
			'end': staff_charge.end.astimezone(timezone.get_current_timezone()).strftime(date_time_format),
			'quantity': str(round(diff.days * 1440 + diff.seconds / 60, 2))
		})
	return result

def get_consumables_for_billing(billing_form: BillingFilterForm) -> List[Dict]:
	result = []
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
	consumable_withdrawal: ConsumableWithdraw
	for consumable_withdrawal in queryset:
		result.append({
			'type': 'consumable',
			'name': consumable_withdrawal.consumable.name,
			'details': '',
			'account': consumable_withdrawal.project.account.name,
			'account_id': consumable_withdrawal.project.account_id,
			'project': consumable_withdrawal.project.name,
			'project_id': consumable_withdrawal.project_id,
			'application': consumable_withdrawal.project.application_identifier,
			'username': consumable_withdrawal.customer.username,
			'user_id': consumable_withdrawal.customer_id,
			'start': consumable_withdrawal.date.astimezone(timezone.get_current_timezone()).strftime(date_time_format),
			'end': consumable_withdrawal.date.astimezone(timezone.get_current_timezone()).strftime(date_time_format),
			'quantity': consumable_withdrawal.quantity
		})
	return result


def get_training_sessions_for_billing(billing_form: BillingFilterForm) -> List[Dict]:
	result = []
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
	training_session: TrainingSession
	for training_session in queryset:
		result.append({
			'type': 'training_session',
			'name': training_session.tool.name,
			'details': f'{training_session.get_type_display()} training provided by {training_session.trainer}',
			'account': training_session.project.account.name,
			'account_id': training_session.project.account_id,
			'project': training_session.project.name,
			'project_id': training_session.project_id,
			'application': training_session.project.application_identifier,
			'username': training_session.trainee.username,
			'user_id': training_session.trainee.id,
			'start': training_session.date.astimezone(timezone.get_current_timezone()).strftime(date_time_format),
			'end': training_session.date.astimezone(timezone.get_current_timezone()).strftime(date_time_format),
			'quantity': training_session.duration
		})
	return result
