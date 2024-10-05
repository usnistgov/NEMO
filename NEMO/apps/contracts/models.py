from datetime import date

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from NEMO.apps.contracts.customization import ContractsCustomization
from NEMO.constants import CHAR_FIELD_MEDIUM_LENGTH, MEDIA_PROTECTED
from NEMO.models import BaseDocumentModel, BaseModel, User


class Procurement(BaseModel):
    name = models.CharField(max_length=CHAR_FIELD_MEDIUM_LENGTH, help_text=_("The name of the contract"))
    submitted_date = models.DateField(null=True, blank=True, help_text=_("The date this contract was submitted"))
    award_date = models.DateField(null=True, blank=True, help_text=_("The date this contract was awarded"))
    contract_number = models.CharField(
        null=True, blank=True, max_length=CHAR_FIELD_MEDIUM_LENGTH, help_text=_("The contract number")
    )
    requisition_number = models.CharField(
        null=True,
        blank=True,
        max_length=CHAR_FIELD_MEDIUM_LENGTH,
        help_text=_("The requisition number for this contract"),
    )
    cost = models.DecimalField(
        null=True, blank=True, decimal_places=2, max_digits=14, help_text=_("The cost of this contract")
    )
    notes = models.TextField(null=True, blank=True)

    def display_name(self):
        return self.name

    def display_cost(self):
        if self.cost:
            return f"{self.cost:,.2f}"

    def __str__(self):
        return self.name

    class Meta:
        ordering = ["name"]


class ServiceContract(Procurement):
    current_year = models.PositiveIntegerField(
        default=1, validators=[MinValueValidator(1)], help_text=_("The total number of years of this service contract")
    )
    total_years = models.PositiveIntegerField(
        default=1, validators=[MinValueValidator(1)], help_text=_("The current year for this service contract")
    )
    start = models.DateField(null=True, blank=True, help_text=_("The start date of this service contract"))
    end = models.DateField(null=True, blank=True, help_text=_("The end date of this service contract"))
    reminder_date = models.DateField(null=True, blank=True, help_text=_("The reminder date for this service contract"))

    def display_name(self):
        return f"{self.name}"

    def display_current_year(self):
        return f"{self.current_year} of {self.total_years}"

    def is_expired(self):
        return self.end and date.today() >= self.end

    def is_warning(self):
        return self.reminder_date and self.end and self.reminder_date <= date.today() < self.end

    def is_active(self):
        return self.start and self.end and self.start <= date.today() <= self.end

    def clean(self):
        if self.current_year > self.total_years:
            raise ValidationError(
                {"current_year": "The current year must be less or equal to the total number of years"}
            )


class ContractorAgreement(BaseModel):
    name = models.CharField(max_length=CHAR_FIELD_MEDIUM_LENGTH, help_text=_("The name of the contractor"))
    contract = models.ForeignKey(
        Procurement,
        null=True,
        blank=True,
        help_text=_("The contract this contractor is linked to"),
        on_delete=models.CASCADE,
    )
    start = models.DateField(null=True, blank=True, help_text=_("Start date of the contractor agreement"))
    end = models.DateField(null=True, blank=True, help_text=_("The end date of this contractor agreement"))
    reminder_date = models.DateField(
        null=True, blank=True, help_text=_("The reminder date for this contractor agreement")
    )
    notes = models.TextField(null=True, blank=True)

    @property
    def contract_name(self) -> str:
        if self.contract:
            return self.contract.name
        else:
            return ContractsCustomization.get("contracts_contractors_default_empty_label")

    @property
    def contract_number(self) -> str:
        if self.contract:
            return self.contract.contract_number

    def is_expired(self):
        return self.end and date.today() >= self.end

    def is_warning(self):
        return self.reminder_date and self.end and self.reminder_date <= date.today() < self.end

    def is_active(self):
        return self.start and self.end and self.start <= date.today() <= self.end

    def __str__(self):
        return f"{self.name} ({self.contract_name})"

    class Meta:
        ordering = ["contract", "-start"]


class ProcurementDocuments(BaseDocumentModel):
    procurement = models.ForeignKey(Procurement, on_delete=models.CASCADE)

    def get_filename_upload(self, filename):
        from django.template.defaultfilters import slugify

        name = slugify(self.procurement.name)
        type_name = "service_contracts" if isinstance(self.procurement, ServiceContract) else "procurements"
        return f"{MEDIA_PROTECTED}/{type_name}/{name}/{filename}"

    class Meta(BaseDocumentModel.Meta):
        verbose_name_plural = "Procurement documents"


class ContractorAgreementDocuments(BaseDocumentModel):
    contractor_agreement = models.ForeignKey(ContractorAgreement, on_delete=models.CASCADE)

    def get_filename_upload(self, filename):
        from django.template.defaultfilters import slugify

        name = slugify(self.contractor_agreement.name)
        return f"{MEDIA_PROTECTED}/contractor_agreements/{name}/{filename}"

    class Meta(BaseDocumentModel.Meta):
        verbose_name_plural = "Contractor agreement documents"
