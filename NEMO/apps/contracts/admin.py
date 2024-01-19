from django import forms
from django.contrib import admin

from NEMO.apps.contracts.customization import ContractsCustomization
from NEMO.apps.contracts.models import (
    ContractorAgreement,
    ContractorAgreementDocuments,
    Procurement,
    ProcurementDocuments,
    ServiceContract,
)
from NEMO.apps.contracts.views.contracts import export_contractor_agreements, export_procurements
from NEMO.mixins import ModelAdminRedirectMixin


@admin.action(description="Export selected procurements in CSV")
def procurements_export_csv(modeladmin, request, queryset):
    return export_procurements(queryset.all(), procurement_only=True)


@admin.action(description="Export selected service contracts in CSV")
def service_contracts_export_csv(modeladmin, request, queryset):
    return export_procurements(queryset.all(), procurement_only=False)


@admin.action(description="Export selected contractor agreements in CSV")
def contractor_agreements_export_csv(modeladmin, request, queryset):
    return export_contractor_agreements(queryset.all())


class ProcurementDocumentsInline(admin.TabularInline):
    model = ProcurementDocuments
    extra = 1


@admin.register(Procurement)
class ProcurementAdmin(ModelAdminRedirectMixin, admin.ModelAdmin):
    list_display = ["name", "submitted_date", "award_date", "contract_number", "requisition_number", "cost"]
    list_filter = ["submitted_date", "award_date", "cost"]
    actions = [procurements_export_csv]
    inlines = [ProcurementDocumentsInline]

    def get_queryset(self, request):
        return super().get_queryset(request).filter(servicecontract__isnull=True)


@admin.register(ServiceContract)
class ServiceContractAdmin(ModelAdminRedirectMixin, admin.ModelAdmin):
    list_display = [
        "get_display_name",
        "get_display_current_year",
        "submitted_date",
        "award_date",
        "contract_number",
        "requisition_number",
        "start",
        "end",
        "reminder_date",
        "cost",
    ]
    list_filter = ["submitted_date", "award_date", "start", "end", "reminder_date", "cost"]
    actions = [service_contracts_export_csv]
    inlines = [ProcurementDocumentsInline]

    @admin.display(description="Name", ordering="name")
    def get_display_name(self, service_contract: ServiceContract):
        return service_contract.display_name()

    @admin.display(description="Current year")
    def get_display_current_year(self, service_contract: ServiceContract):
        return service_contract.display_current_year()

    def get_fields(self, request, obj=None):
        fields = super().get_fields(request, obj)
        fields.insert(1, fields.pop(fields.index("total_years")))
        fields.insert(1, fields.pop(fields.index("current_year")))
        fields.insert(len(fields) - 5, fields.pop(fields.index("reminder_date")))
        fields.insert(len(fields) - 5, fields.pop(fields.index("end")))
        fields.insert(len(fields) - 5, fields.pop(fields.index("start")))
        return fields


class ContractorAgreementDocumentsInline(admin.TabularInline):
    model = ContractorAgreementDocuments
    extra = 1


class ContractorAgreementAdminForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "contract" in self.fields:
            self.fields["contract"].empty_label = ContractsCustomization.get(
                "contracts_contractors_default_empty_label"
            )


@admin.register(ContractorAgreement)
class ContractorAgreementAdmin(ModelAdminRedirectMixin, admin.ModelAdmin):
    list_display = ["name", "get_contract_name", "get_contract_number", "start", "end", "reminder_date"]
    list_filter = ["start", "end", "reminder_date", "contract"]
    actions = [contractor_agreements_export_csv]
    inlines = [ContractorAgreementDocumentsInline]
    form = ContractorAgreementAdminForm

    @admin.display(description="Contract name", ordering="contract__name")
    def get_contract_name(self, contractor_agreement: ContractorAgreement):
        return contractor_agreement.contract_name

    @admin.display(description="Contract number", ordering="contract__contract_number")
    def get_contract_number(self, contractor_agreement: ContractorAgreement):
        return contractor_agreement.contract_number
