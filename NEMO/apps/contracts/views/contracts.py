import datetime

from django.contrib.auth.decorators import login_required, permission_required, user_passes_test
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from NEMO.apps.contracts.customization import ContractsCustomization
from NEMO.apps.contracts.models import ContractorAgreement, Procurement, ServiceContract
from NEMO.models import EmailNotificationType, User
from NEMO.typing import QuerySetType
from NEMO.utilities import (
	BasicDisplayTable,
	EmailCategory,
	export_format_datetime,
	format_datetime,
	get_email_from_settings,
	send_mail,
)
from NEMO.views.pagination import SortedPaginator


def contract_permission(user):
	staff = ContractsCustomization.get_bool("contracts_view_staff")
	user_office = ContractsCustomization.get_bool("contracts_view_user_office")
	accounting = ContractsCustomization.get_bool("contracts_view_accounting_officer")
	return user.is_active and (
		staff
		and user.is_staff
		or user_office
		and user.is_user_office
		or accounting
		and user.is_accounting_officer
		or user.is_facility_manager
		or user.is_superuser
	)


@login_required
@user_passes_test(contract_permission)
@require_GET
def service_contracts(request):
	service_contract_list = ServiceContract.objects.all()
	page = SortedPaginator(service_contract_list, request, order_by="name").get_current_page()

	if bool(request.GET.get("csv", False)):
		return export_procurements(service_contract_list, procurement_only=False)

	return render(request, "contracts/service_contracts.html", {"page": page})


@login_required
@user_passes_test(contract_permission)
@require_GET
def procurements(request):
	procurement_list = Procurement.objects.filter(servicecontract__isnull=True)
	page = SortedPaginator(procurement_list, request, order_by="name").get_current_page()

	if bool(request.GET.get("csv", False)):
		return export_procurements(procurement_list, procurement_only=True)

	return render(request, "contracts/procurements.html", {"page": page})


@login_required
@user_passes_test(contract_permission)
@require_GET
def contractors(request):
	contractor_list = ContractorAgreement.objects.filter()
	page = SortedPaginator(contractor_list, request, order_by="name").get_current_page()

	if bool(request.GET.get("csv", False)):
		return export_contractor_agreements(contractor_list)

	return render(request, "contracts/contractors.html", {"page": page})


def export_procurements(procurement_list: QuerySetType[Procurement], procurement_only=True):
	table = get_procurements_table_display(procurement_list, procurement_only)
	filename = f"{'procurements' if procurement_only else 'service_contracts'}_{export_format_datetime()}.csv"
	response = table.to_csv()
	response["Content-Disposition"] = f'attachment; filename="{filename}"'
	return response


def export_contractor_agreements(contractor_agreement_list: QuerySetType[ContractorAgreement]):
	table = get_contractors_table_display(contractor_agreement_list)
	filename = f"contractor_agreements_{export_format_datetime()}.csv"
	response = table.to_csv()
	response["Content-Disposition"] = f'attachment; filename="{filename}"'
	return response


@login_required
@require_GET
@permission_required("NEMO.trigger_timed_services", raise_exception=True)
def email_contract_reminders(request):
	return send_email_contract_reminders()


def get_procurements_table_display(
		procurement_list: QuerySetType[Procurement], procurement_only=True
) -> BasicDisplayTable:
	table = BasicDisplayTable()
	table.add_header(("name", "General info")),
	if not procurement_only:
		table.add_header(("current_year", "Year")),
	table.add_header(("submitted_date", "Submitted date")),
	table.add_header(("award_date", "Award date")),
	if not procurement_only:
		table.add_header(("renewal_date", "Renewal date")),
	table.add_header(("contract_number", "Contract number")),
	table.add_header(("requisition_number", "Requisition number")),
	table.add_header(("cost", "Cost")),
	table.add_header(("notes", "Notes")),
	for procurement in procurement_list:
		row = {
			"name": procurement.display_name(),
			"contract_number": procurement.contract_number,
			"requisition_number": procurement.requisition_number,
			"cost": procurement.display_cost(),
			"notes": procurement.notes,
		}
		if procurement.submitted_date:
			row["submitted_date"] = format_datetime(procurement.submitted_date)
		if procurement.award_date:
			row["award_date"] = format_datetime(procurement.award_date)
		if not procurement_only and isinstance(procurement, ServiceContract):
			row["current_year"] = procurement.display_current_year()
			if procurement.renewal_date:
				row["renewal_date"] = format_datetime(procurement.renewal_date)
		table.add_row(row)
	return table


def get_contractors_table_display(contractor_agreement_list: QuerySetType[ContractorAgreement]) -> BasicDisplayTable:
	table = BasicDisplayTable()
	table.headers = [
		("name", "Name"),
		("contract_name", "Contract"),
		("contract_number", "Contract number"),
		("start", "Start"),
		("end", "End"),
		("notes", "Notes"),
	]
	for contractor_agreement in contractor_agreement_list:
		table.add_row(
			{
				"name": contractor_agreement.name,
				"contract_name": contractor_agreement.contract_name,
				"contract_number": contractor_agreement.contract_number,
				"start": format_datetime(contractor_agreement.start) if contractor_agreement.start else "",
				"end": format_datetime(contractor_agreement.end) if contractor_agreement.end else "",
				"notes": contractor_agreement.notes or '',
			}
		)
	return table


def send_email_contract_reminders():
	for reminder_days in ContractsCustomization.get_list_int("contracts_renewal_reminder_days"):
		renewal_date = datetime.date.today() + datetime.timedelta(days=reminder_days)
		table = get_procurements_table_display(ServiceContract.objects.filter(renewal_date=renewal_date))
		send_reminder(table, "service contracts", reminder_days, renewal_date)
	for reminder_days in ContractsCustomization.get_list_int("contracts_contractors_reminder_days"):
		end_date = datetime.date.today() + datetime.timedelta(days=reminder_days)
		table = get_contractors_table_display(ContractorAgreement.objects.filter(end=end_date))
		send_reminder(table, "contractor agreements", reminder_days, end_date)
	return HttpResponse()


def send_reminder(table: BasicDisplayTable, items_name: str, reminder_days: int, renewal_date):
	emails = [
		email
		for manager in User.objects.filter(is_active=True, is_facility_manager=True)
		for email in manager.get_emails(EmailNotificationType.BOTH_EMAILS)
	]
	if table and table.rows:
		message = "Hello,<br><br>\n\n"
		message += f"This email is to inform you that the following {items_name} are expiring in {reminder_days} day{'s' if reminder_days > 1 else ''} on {format_datetime(renewal_date)}:<br><br>\n\n"
		message += basic_table_to_html(table)
		subject = f"{items_name.capitalize()} expiring in {reminder_days} days"
		send_mail(
			subject=subject,
			content=message,
			from_email=get_email_from_settings(),
			to=emails,
			email_category=EmailCategory.TIMED_SERVICES,
		)


def basic_table_to_html(table: BasicDisplayTable) -> str:
	style = ' style="padding: 5px; border: 1px solid black"'
	result = '<table style="border-collapse: collapse"><thead><tr>'
	for header in table.flat_headers():
		result += f"<th {style}>{header.capitalize()}</th>"
	result += "</tr></thead><tbody>"
	for row in table.rows:
		result += "<tr>"
		for cell_value in [row.get(key, "") for key, display_value in table.headers]:
			result += f"<td {style}>{cell_value or ''}</td>"
		result += "</tr>"
	result += "</tbody></table>"
	return result
