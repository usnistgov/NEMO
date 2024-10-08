from typing import Optional

from django import forms
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from NEMO.apps.credit_card_orders.customization import CreditCardOrderCustomization
from NEMO.apps.credit_card_orders.models import (
    CreditCardOrder,
    CreditCardOrderApprovalLevel,
    CreditCardOrderDocuments,
    CreditCardOrderPDFTemplate,
)
from NEMO.decorators import administrator_required
from NEMO.exceptions import RequiredUnansweredQuestionsException
from NEMO.models import User
from NEMO.typing import QuerySetType
from NEMO.utilities import BasicDisplayTable, export_format_datetime, format_datetime
from NEMO.views.pagination import SortedPaginator
from NEMO.widgets.dynamic_form import DynamicForm, render_group_questions


def can_view_cc_order(user) -> bool:
    staff = CreditCardOrderCustomization.get_bool("credit_card_order_view_staff")
    user_office = CreditCardOrderCustomization.get_bool("credit_card_order_view_user_office")
    accounting = CreditCardOrderCustomization.get_bool("credit_card_order_view_accounting_officer")
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


def can_create_cc_order(user: User) -> bool:
    staff = CreditCardOrderCustomization.get_bool("credit_card_order_create_staff")
    user_office = CreditCardOrderCustomization.get_bool("credit_card_order_create_user_office")
    accounting = CreditCardOrderCustomization.get_bool("credit_card_order_create_accounting_officer")
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


def can_approve_cc_order(user: User, credit_card_order: CreditCardOrder, level_id=None) -> bool:
    reviewers = credit_card_order.next_approval_candidates()
    self_approval_allowed = CreditCardOrderCustomization.get_bool("credit_card_order_self_approval_allowed")
    if not self_approval_allowed and credit_card_order.creator in reviewers:
        reviewers.remove(credit_card_order.creator)
    return user in reviewers


def can_edit_cc_order(user: User, credit_card_order: CreditCardOrder) -> bool:
    if credit_card_order.cancelled or credit_card_order.status in [
        CreditCardOrder.OrderStatus.DENIED,
        CreditCardOrder.OrderStatus.FULFILLED,
    ]:
        return False
    return can_create_cc_order(user) or can_approve_cc_order(user, credit_card_order)


class CreditCardOrderForm(forms.ModelForm):
    class Meta:
        model = CreditCardOrder
        exclude = [
            "status",
            "template",
            "template_data",
            "creator",
            "cancelled",
            "cancelled_by",
            "cancellation_time",
            "cancellation_reason",
        ]


@login_required
@user_passes_test(can_view_cc_order)
@require_GET
def credit_card_orders(request):
    credit_card_order_list = CreditCardOrder.objects.filter(cancelled=False)
    page = SortedPaginator(credit_card_order_list, request, order_by="-last_updated").get_current_page()

    if bool(request.GET.get("csv", False)):
        return export_credit_card_orders(credit_card_order_list.order_by("-last_updated"))

    dictionary = {
        "page": page,
        "pdf_templates": CreditCardOrderPDFTemplate.objects.all(),
        "user_can_add": can_create_cc_order(request.user),
        "self_approval_allowed": CreditCardOrderCustomization.get_bool("credit_card_order_self_approval_allowed"),
    }
    return render(request, "credit_card_orders/orders.html", dictionary)


def export_credit_card_orders(credit_card_orders_list: QuerySetType[CreditCardOrder]):
    table = BasicDisplayTable()
    table.add_header(("order_number", "Order number")),
    table.add_header(("created_date", "Created date")),
    table.add_header(("created_by", "Created by")),
    table.add_header(("status", "Status")),
    table.add_header(("cancelled", "Cancelled")),
    table.add_header(("cancelled_by", "Cancelled by")),
    table.add_header(("cancellation_reason", "Cancellation reason")),
    table.add_header(("notes", "Notes")),
    table.add_header(("documents", "Documents")),
    for credit_card_order in credit_card_orders_list:
        row = {
            "order_number": credit_card_order.order_number,
            "created_date": format_datetime(credit_card_order.creation_time, "SHORT_DATE_FORMAT"),
            "created_by": credit_card_order.creator,
            "status": credit_card_order.get_status_display(),
            "cancelled": format_datetime(credit_card_order.cancellation_time, "SHORT_DATE_FORMAT"),
            "cancelled_by": credit_card_order.cancelled_by,
            "cancellation_reason": credit_card_order.cancellation_reason,
            "notes": credit_card_order.notes or "",
            "documents": "\n".join([doc.full_link() for doc in credit_card_order.creditcardorderdocuments_set.all()]),
        }
        table.add_row(row)
    filename = f"credit_card_orders_{export_format_datetime()}.csv"
    response = table.to_csv()
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@administrator_required
@require_GET
def credit_card_order_templates(request):
    credit_card_order_template_list = CreditCardOrderPDFTemplate.objects.all()
    page = SortedPaginator(credit_card_order_template_list, request, order_by="name").get_current_page()

    return render(request, "credit_card_orders/order_templates.html", {"page": page})


@login_required
@require_http_methods(["GET", "POST"])
def create_credit_card_order(request, pdf_template_id=None, credit_card_order_id=None):
    user: User = request.user

    try:
        cc_order: Optional[CreditCardOrder] = CreditCardOrder.objects.get(id=credit_card_order_id)
        pdf_template = cc_order.template
    except CreditCardOrder.DoesNotExist:
        cc_order = None
        if not can_create_cc_order(user):
            return redirect("landing")
        # only check for pdf template if it's a new order
        templates: QuerySetType[CreditCardOrderPDFTemplate] = CreditCardOrderPDFTemplate.objects.all()
        try:
            if templates.count() == 1:
                pdf_template = templates.first()
            else:
                pdf_template = CreditCardOrderPDFTemplate.objects.get(id=pdf_template_id)
        except CreditCardOrderPDFTemplate.DoesNotExist:
            return render(request, "credit_card_orders/choose_template.html", {"pdf_templates": templates})

    edit = bool(cc_order)

    form = CreditCardOrderForm(request.POST or None, instance=cc_order)

    if edit and not can_edit_cc_order(user, cc_order):
        if cc_order.cancelled:
            form.add_error(None, "You are not allowed to edit cancelled orders.")
        elif cc_order.status in [CreditCardOrder.OrderStatus.DENIED, CreditCardOrder.OrderStatus.FULFILLED]:
            form.add_error(None, f"You are not allowed to edit {cc_order.get_status_display().lower()} orders.")
        else:
            form.add_error(None, "You are not allowed to edit this order.")

    dictionary = {
        "dynamic_form_fields": DynamicForm(pdf_template.form_fields, cc_order.template_data if edit else None).render(
            "credit_card_orders_form_fields_group", pdf_template.id
        ),
        "selected_template_id": pdf_template.id,
    }

    if request.method == "POST":
        try:
            form.instance.template_data = DynamicForm(pdf_template.form_fields).extract(request)
        except RequiredUnansweredQuestionsException as e:
            form.add_error("template_data", e.msg)
        if form.is_valid():
            if not edit:
                form.instance.creator = user

            form.instance.last_updated_by = user
            form.instance.template = pdf_template
            new_cc_order = form.save()

            # Handle file uploads
            for f in request.FILES.getlist("order_documents"):
                CreditCardOrderDocuments.objects.create(document=f, credit_card_order=new_cc_order)
            CreditCardOrderDocuments.objects.filter(id__in=request.POST.getlist("remove_documents")).delete()

            # create_credit_card_order_notification(new_cc_order)
            # send_order_received_email(request, new_cc_order, edit)
            return redirect("credit_card_orders")
        else:
            if request.FILES.getlist("order_documents") or request.POST.get("remove_documents"):
                form.add_error(field=None, error="Credit card order document changes were lost, please resubmit them.")

    # If GET request or form is not valid
    dictionary["form"] = form
    return render(request, "credit_card_orders/order.html", dictionary)


@login_required
@require_GET
def approve_credit_card_order(request, credit_card_order_id, approved=None):
    # TODO: finish and test this
    user: User = request.user
    cc_order = get_object_or_404(CreditCardOrder, pk=credit_card_order_id)
    if not cc_order.next_approval_level():
        return redirect("landing")
    approval_level = get_object_or_404(CreditCardOrderApprovalLevel, pk=cc_order.next_approval_level().id)
    if not can_approve_cc_order(user, cc_order, cc_order.next_approval_level().id):
        return redirect("landing")
    if approved is None:
        return render(request, "credit_card_orders/order_approval.html", {"credit_card_order": cc_order})
    else:
        cc_order.process_approval(user, approval_level, approved)
    return redirect("credit_card_orders")


@login_required
@require_GET
def render_credit_card_order_pdf(request, credit_card_order_id):
    user: User = request.user
    cc_order = get_object_or_404(CreditCardOrder, pk=credit_card_order_id)
    if not can_view_cc_order(user) or not can_edit_cc_order(user, cc_order) or not can_create_cc_order(user):
        return redirect("landing")
    pdf_response = HttpResponse(content_type="application/pdf")
    pdf_response["Content-Disposition"] = "attachment; filename=form.pdf"
    pdf_response.write(cc_order.get_filled_pdf_template())
    return pdf_response


@login_required
@require_GET
def form_fields_group(request, form_id, group_name):
    template = get_object_or_404(CreditCardOrderPDFTemplate, id=form_id)
    return HttpResponse(
        render_group_questions(
            request, template.form_fields, "credit_card_orders_form_fields_group", form_id, group_name
        )
    )


# TODO: figure this out
# def set_order_number_from_template(credit_card_order: CreditCardOrder, user: User) -> str:
#     order_number_template_enabled = CreditCardOrderCustomization.get_bool("credit_card_order_number_template_enabled")
#     order_number_template = CreditCardOrderCustomization.get("credit_card_order_number_template")
#     if order_number_template_enabled and order_number_template:
#         order_number = Template(order_number_template).render(Context({"user": user}))
#         return order_number
