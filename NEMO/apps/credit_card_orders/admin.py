import json

from django import forms
from django.contrib import admin
from django.utils.safestring import mark_safe

from NEMO.apps.credit_card_orders.models import (
    CreditCardOrder,
    CreditCardOrderApproval,
    CreditCardOrderApprovalLevel,
    CreditCardOrderDocumentType,
    CreditCardOrderDocuments,
    CreditCardOrderPDFTemplate,
    CreditCardOrderSpecialMapping,
)
from NEMO.fields import DatalistWidget
from NEMO.widgets.dynamic_form import DynamicForm


class CreditCardOrderApprovalLevelFormset(forms.BaseInlineFormSet):
    model = CreditCardOrderApprovalLevel

    def add_fields(self, form, index):
        super().add_fields(form, index)
        form.fields["permission"] = forms.ChoiceField(
            choices=CreditCardOrderApprovalLevel.permission_choices(), widget=DatalistWidget
        )


class CreditCardOrderSpecialMappingFormset(forms.BaseInlineFormSet):
    model = CreditCardOrderSpecialMapping

    def add_fields(self, form, index):
        super().add_fields(form, index)
        form.fields["field_value_approval"].queryset = CreditCardOrderApprovalLevel.objects.filter(
            template=self.instance
        )


class CreditCardOrderApprovalLevelAdminInline(admin.TabularInline):
    model = CreditCardOrderApprovalLevel
    formset = CreditCardOrderApprovalLevelFormset


class CreditCardOrderSpecialMappingAdminInline(admin.TabularInline):
    model = CreditCardOrderSpecialMapping
    formset = CreditCardOrderSpecialMappingFormset


class CreditCardOrderPDFTemplateForm(forms.ModelForm):

    class Media:
        js = ("admin/dynamic_form_preview/dynamic_form_preview.js",)
        css = {"": ("admin/dynamic_form_preview/dynamic_form_preview.css",)}

    def clean_form_fields(self):
        questions = self.cleaned_data["form_fields"]
        try:
            return json.dumps(json.loads(questions), indent=4)
        except:
            pass
        return questions


@admin.register(CreditCardOrderPDFTemplate)
class CreditCardOrderPDFTemplateAdmin(admin.ModelAdmin):
    form = CreditCardOrderPDFTemplateForm
    list_display = ["name", "form"]
    inlines = [CreditCardOrderApprovalLevelAdminInline, CreditCardOrderSpecialMappingAdminInline]
    readonly_fields = ["_form_fields_preview"]

    def _form_fields_preview(self, obj: CreditCardOrderPDFTemplate):
        if obj.id:
            form_validity_div = '<div id="form_validity"></div>' if obj.form_fields else ""
            return mark_safe(
                '<div class="dynamic_form_preview">{}{}</div><div class="help dynamic_form_preview_help">Save form to preview form fields</div>'.format(
                    DynamicForm(obj.form_fields).render("credit_card_orders_form_fields_group", obj.id),
                    form_validity_div,
                )
            )


class CreditCardOrderApprovalInline(admin.TabularInline):
    model = CreditCardOrderApproval

    def __init__(self, parent_model, admin_site):
        super().__init__(parent_model, admin_site)


class CreditCardOrderDocumentsInline(admin.TabularInline):
    model = CreditCardOrderDocuments
    extra = 1


@admin.register(CreditCardOrderDocumentType)
class CreditCardOrderDocumentTypeAdmin(admin.ModelAdmin):
    list_display = ["name", "display_order"]


@admin.register(CreditCardOrder)
class CreditCardOrderAdmin(admin.ModelAdmin):
    inlines = [CreditCardOrderDocumentsInline, CreditCardOrderApprovalInline]
    list_display = ["order_number", "status", "last_updated", "creator", "template", "cancelled"]
    list_filter = [
        ("creator", admin.RelatedOnlyFieldListFilter),
        ("template", admin.RelatedOnlyFieldListFilter),
        "cancelled",
    ]
    date_hierarchy = "last_updated"
