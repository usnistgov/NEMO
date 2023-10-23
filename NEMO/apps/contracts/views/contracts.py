import datetime

from django.contrib.auth.decorators import login_required, permission_required, user_passes_test
from django.db.models import CharField
from django.db.models.functions import Cast, Concat
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET

from NEMO.apps.contracts.customization import ContractsCustomization
from NEMO.apps.contracts.models import ContractorAgreement, Procurement, ServiceContract
from NEMO.models import EmailNotificationType, User
from NEMO.templatetags.custom_tags_and_filters import admin_edit_url
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
    service_contract_list = ServiceContract.objects.annotate(
        natural_end=Concat(
            Cast("end", CharField()),
            "name",
            "current_year",
            output_field=CharField(),
        )
    )
    page = SortedPaginator(service_contract_list, request, order_by="-natural_end").get_current_page()

    if bool(request.GET.get("csv", False)):
        return export_procurements(service_contract_list.order_by("-natural_end"), procurement_only=False)

    return render(request, "contracts/service_contracts.html", {"page": page})


@login_required
@user_passes_test(contract_permission)
@require_GET
def procurements(request):
    procurement_list = Procurement.objects.filter(servicecontract__isnull=True)
    page = SortedPaginator(procurement_list, request, order_by="-submitted_date").get_current_page()

    if bool(request.GET.get("csv", False)):
        return export_procurements(procurement_list.order_by("-submitted_date"), procurement_only=True)

    return render(request, "contracts/procurements.html", {"page": page})


@login_required
@user_passes_test(contract_permission)
@require_GET
def contractors(request):
    contractor_list = ContractorAgreement.objects.annotate(
        natural_end=Concat(
            Cast("end", CharField()),
            "name",
            output_field=CharField(),
        )
    )
    page = SortedPaginator(contractor_list, request, order_by="-natural_end").get_current_page()

    if bool(request.GET.get("csv", False)):
        return export_contractor_agreements(contractor_list.order_by("-natural_end"))

    return render(request, "contracts/contractors.html", {"page": page})


@login_required
@user_passes_test(lambda u: u.is_active and u.has_perm(f"contract.change_servicecontract"))
def service_contract_renew(request, service_contract_id):
    service_contract = get_object_or_404(ServiceContract, pk=service_contract_id)
    current_year = service_contract.current_year
    new_current_year = current_year + 1 if current_year != service_contract.total_years else 1
    new_service_contract = ServiceContract.objects.create(
        name=service_contract.name,
        current_year=new_current_year,
        total_years=service_contract.total_years,
    )
    redirect_url = reverse("service_contracts")
    return redirect(admin_edit_url({"request": request}, new_service_contract, redirect_url=redirect_url))


@login_required
@user_passes_test(lambda u: u.is_active and u.has_perm(f"contract.change_contractoragreement"))
def contractor_agreement_renew(request, contractor_agreement_id):
    contractor = get_object_or_404(ContractorAgreement, pk=contractor_agreement_id)
    new_contractor = ContractorAgreement.objects.create(name=contractor.name, start=contractor.end)
    redirect_url = reverse("contractor_agreements")
    return redirect(admin_edit_url({"request": request}, new_contractor, redirect_url=redirect_url))


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
        table.add_header(("start", "Start date")),
        table.add_header(("end", "End date")),
        table.add_header(("reminder_date", "Reminder date")),
    table.add_header(("contract_number", "Contract number")),
    table.add_header(("requisition_number", "Requisition number")),
    table.add_header(("cost", "Cost")),
    table.add_header(("notes", "Notes")),
    table.add_header(("documents", "Documents")),
    for procurement in procurement_list:
        row = {
            "name": procurement.display_name(),
            "contract_number": procurement.contract_number,
            "requisition_number": procurement.requisition_number,
            "cost": procurement.display_cost(),
            "notes": procurement.notes or "",
            "documents": "\n".join([doc.full_link() for doc in procurement.procurementdocuments_set.all()]),
        }
        if procurement.submitted_date:
            row["submitted_date"] = format_datetime(procurement.submitted_date, "SHORT_DATE_FORMAT")
        if procurement.award_date:
            row["award_date"] = format_datetime(procurement.award_date, "SHORT_DATE_FORMAT")
        if not procurement_only and isinstance(procurement, ServiceContract):
            row["current_year"] = procurement.display_current_year()
            if procurement.end:
                row["end"] = format_datetime(procurement.end, "SHORT_DATE_FORMAT")
            if procurement.start:
                row["start"] = format_datetime(procurement.start, "SHORT_DATE_FORMAT")
            if procurement.reminder_date:
                row["reminder_date"] = format_datetime(procurement.reminder_date, "SHORT_DATE_FORMAT")
        table.add_row(row)
    return table


def get_contractors_table_display(contractor_agreement_list: QuerySetType[ContractorAgreement]) -> BasicDisplayTable:
    table = BasicDisplayTable()
    table.headers = [
        ("name", "Name"),
        ("contract_name", "Contract"),
        ("contract_number", "Contract number"),
        ("start", "Start date"),
        ("end", "End date"),
        ("reminder", "Reminder date"),
        ("notes", "Notes"),
        ("documents", "Documents"),
    ]
    for contractor_agreement in contractor_agreement_list:
        table.add_row(
            {
                "name": contractor_agreement.name,
                "contract_name": contractor_agreement.contract_name,
                "contract_number": contractor_agreement.contract_number,
                "start": format_datetime(contractor_agreement.start, "SHORT_DATE_FORMAT")
                if contractor_agreement.start
                else "",
                "end": format_datetime(contractor_agreement.end, "SHORT_DATE_FORMAT")
                if contractor_agreement.end
                else "",
                "reminder_date": format_datetime(contractor_agreement.reminder_date, "SHORT_DATE_FORMAT")
                if contractor_agreement.reminder_date
                else "",
                "notes": contractor_agreement.notes or "",
                "documents": "\n".join(
                    [doc.full_link() for doc in contractor_agreement.contractoragreementdocuments_set.all()]
                ),
            }
        )
    return table


def send_email_contract_reminders():
    sc_table = get_procurements_table_display(
        ServiceContract.objects.filter(reminder_date=datetime.date.today()), procurement_only=False
    )
    ca_table = get_contractors_table_display(ContractorAgreement.objects.filter(reminder_date=datetime.date.today()))
    send_reminder(sc_table, "service contracts")
    send_reminder(ca_table, "contractor agreements")
    return HttpResponse()


def send_reminder(table: BasicDisplayTable, items_name: str):
    emails = [
        email
        for manager in User.objects.filter(is_active=True, is_facility_manager=True)
        for email in manager.get_emails(EmailNotificationType.BOTH_EMAILS)
    ]
    if table and table.rows:
        message = "Hello,<br><br>\n\n"
        message += f"This email is a reminder to start the renewal process for the following {items_name}:<br><br>\n\n"
        message += basic_table_to_html(table)
        subject = f"{items_name.capitalize()} renewal reminder"
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
