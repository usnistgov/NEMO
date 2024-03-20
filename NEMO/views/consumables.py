from datetime import date
from logging import getLogger
from typing import List

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Q
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from NEMO.decorators import user_office_or_manager_required
from NEMO.exceptions import ProjectChargeException
from NEMO.forms import ConsumableWithdrawForm, RecurringConsumableChargeForm
from NEMO.models import Consumable, ConsumableWithdraw, RecurringConsumableCharge, User
from NEMO.policy import policy_class as policy
from NEMO.utilities import (
    BasicDisplayTable,
    EmailCategory,
    as_timezone,
    export_format_datetime,
    format_datetime,
    queryset_search_filter,
    render_email_template,
    send_mail,
    slugify_underscore,
)
from NEMO.views.customization import (
    ApplicationCustomization,
    EmailsCustomization,
    RecurringChargesCustomization,
    get_media_file_contents,
)
from NEMO.views.pagination import SortedPaginator

consumables_logger = getLogger(__name__)


def consumable_permissions(user):
    user_allowed = ApplicationCustomization.get_bool("consumable_user_self_checkout")
    return user.is_active and (user_allowed or user.is_staff or user.is_user_office or user.is_superuser)


def self_checkout(user) -> bool:
    return user.is_active and not (user.is_staff or user.is_user_office or user.is_superuser)


@login_required
@user_passes_test(consumable_permissions)
@require_http_methods(["GET", "POST"])
def consumables(request):
    user: User = request.user
    is_self_checkout = self_checkout(user)
    if request.method == "GET":
        from NEMO.rates import rate_class

        rate_dict = rate_class.get_consumable_rates(Consumable.objects.all())
        consumable_list = Consumable.objects.filter(visible=True).order_by("category", "name")
        if is_self_checkout:
            consumable_list = consumable_list.filter(allow_self_checkout=True).filter(
                Q(self_checkout_only_users__isnull=True) | Q(self_checkout_only_users__in=[user])
            )

        dictionary = {
            "users": User.objects.filter(is_active=True),
            "consumables": consumable_list,
            "rates": rate_dict,
            "self_checkout": is_self_checkout,
        }
        if is_self_checkout:
            dictionary["projects"] = user.active_projects().filter(allow_consumable_withdrawals=True)
        return render(request, "consumables/consumables.html", dictionary)
    elif request.method == "POST":
        updated_post_data = request.POST.copy()
        if is_self_checkout:
            updated_post_data.update({"customer": user.id})
        form = ConsumableWithdrawForm(updated_post_data)
        if form.is_valid():
            withdraw = form.save(commit=False)
            customer_allowed = (
                not withdraw.consumable.self_checkout_only_users.exists()
                or withdraw.customer in withdraw.consumable.self_checkout_only_users.all()
            )
            if is_self_checkout and (not withdraw.consumable.allow_self_checkout or not customer_allowed):
                return HttpResponseBadRequest("You can not self checkout this consumable")
            try:
                policy.check_billing_to_project(withdraw.project, withdraw.customer, withdraw.consumable, withdraw)
            except ProjectChargeException as e:
                return HttpResponseBadRequest(e.msg)
            add_withdraw_to_session(request, withdraw)
        else:
            return HttpResponseBadRequest(form.errors.as_ul())
        return render(request, "consumables/consumables_order.html")


def add_withdraw_to_session(request, withdrawal: ConsumableWithdraw):
    request.session.setdefault("withdrawals", [])
    withdrawals: List = request.session.get("withdrawals")
    if withdrawals is not None:
        withdrawal_dict = {
            "customer": str(withdrawal.customer),
            "customer_id": withdrawal.customer_id,
            "consumable": str(withdrawal.consumable),
            "consumable_id": withdrawal.consumable_id,
            "project": str(withdrawal.project),
            "project_id": withdrawal.project_id,
            "quantity": withdrawal.quantity,
        }
        withdrawals.append(withdrawal_dict)
    request.session["withdrawals"] = withdrawals


@login_required
@user_passes_test(consumable_permissions)
@require_GET
def remove_withdraw_at_index(request, index: str):
    try:
        index = int(index)
        withdrawals: List = request.session.get("withdrawals")
        if withdrawals:
            del withdrawals[index]
            request.session["withdrawals"] = withdrawals
    except Exception as e:
        consumables_logger.exception(e)
    return render(request, "consumables/consumables_order.html")


@login_required
@user_passes_test(consumable_permissions)
@require_GET
def clear_withdrawals(request):
    if "withdrawals" in request.session:
        del request.session["withdrawals"]
    return render(request, "consumables/consumables_order.html")


@login_required
@user_passes_test(consumable_permissions)
@require_POST
def make_withdrawals(request):
    user: User = request.user
    withdrawals: List = request.session.setdefault("withdrawals", [])
    force_customer = user.id if self_checkout(user) else None
    for withdraw in withdrawals:
        make_withdrawal(
            consumable_id=withdraw["consumable_id"],
            merchant=request.user,
            customer_id=force_customer or withdraw["customer_id"],
            quantity=withdraw["quantity"],
            project_id=withdraw["project_id"],
            request=request,
        )
    del request.session["withdrawals"]
    return redirect("consumables")


@user_office_or_manager_required
@require_GET
def recurring_charges(request):
    page = SortedPaginator(RecurringConsumableCharge.objects.all(), request, order_by="name").get_current_page()
    dictionary = {"page": page, "extended_permissions": extended_permissions(request)}
    return render(request, "consumables/recurring_charges.html", dictionary)


@user_office_or_manager_required
@require_GET
def search_recurring_charges(request):
    return queryset_search_filter(
        RecurringConsumableCharge.objects.all(),
        ["name", "customer__first_name", "customer__last_name", "customer__username", "project__name"],
        request,
        display="search_display",
    )


@user_office_or_manager_required
@require_GET
def export_recurring_charges(request):
    all_one_quantity = set(list(RecurringConsumableCharge.objects.values_list("quantity", flat=True)))
    table = BasicDisplayTable()
    table.add_header(("name", "Name"))
    if len(all_one_quantity) > 1:
        table.add_header(("quantity", "Quantity"))
    table.add_header(("item", "Item"))
    table.add_header(("customer", "Customer"))
    table.add_header(("project", "Project"))
    table.add_header(("frequency", "Frequency"))
    table.add_header(("last_charge", "Last charge"))
    table.add_header(("next_charge", "Next charge"))
    table.add_header(("errors", "Errors"))

    for charge in RecurringConsumableCharge.objects.all():
        next_charge = charge.next_charge()
        errors = []
        if not charge.is_empty() and not next_charge:
            errors.append("This item expired")
        if charge.invalid_customer():
            errors.append(charge.invalid_customer())
        if charge.invalid_project():
            errors.append(charge.invalid_project())
        table.add_row(
            {
                "name": charge.name,
                "quantity": charge.quantity,
                "item": charge.consumable,
                "customer": charge.customer,
                "project": charge.project,
                "frequency": charge.get_recurrence_display(),
                "last_charge": format_datetime(charge.last_charge, "SHORT_DATETIME_FORMAT"),
                "next_charge": format_datetime(next_charge, "SHORT_DATETIME_FORMAT"),
                "errors": ", ".join(errors),
            }
        )

    response = table.to_csv()
    feature_name = RecurringChargesCustomization.get("recurring_charges_name")
    filename = f"{slugify_underscore(feature_name.lower())}_{export_format_datetime()}.csv"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@user_office_or_manager_required
@require_http_methods(["GET", "POST"])
def create_recurring_charge(request, recurring_charge_id: int = None):
    try:
        instance = RecurringConsumableCharge.objects.get(pk=recurring_charge_id)
    except RecurringConsumableCharge.DoesNotExist:
        instance = None
    locked = not extended_permissions(request)
    if not recurring_charge_id and locked:
        return redirect("login")
    form = RecurringConsumableChargeForm(request.POST or None, instance=instance, locked=locked)
    recurring_charges_category = RecurringChargesCustomization.get_int("recurring_charges_category")
    consumables_options = Consumable.objects.filter(visible=True).order_by("category", "name")
    if recurring_charges_category:
        consumables_options = consumables_options.filter(category_id=recurring_charges_category)
    dictionary = {
        "form": form,
        "users": User.objects.filter(is_active=True),
        "can_charge": not instance
        or not instance.last_charge
        or as_timezone(instance.last_charge).date() != date.today(),
        "force_quantity": RecurringChargesCustomization.get_int("recurring_charges_force_quantity", None),
        "consumables": consumables_options,
    }
    if request.method == "POST":
        if form.is_valid():
            obj: RecurringConsumableCharge = form.save(commit=False)
            if "save_and_charge" in request.POST:
                obj.save_and_charge_with_user(request.user)
            else:
                obj.save_with_user(request.user)
            return redirect("recurring_charges")
    return render(request, "consumables/recurring_charge.html", dictionary)


@user_office_or_manager_required
@require_GET
def delete_recurring_charge(request, recurring_charge_id: int):
    if not extended_permissions(request):
        return redirect("login")
    recurring_charge = get_object_or_404(RecurringConsumableCharge, pk=recurring_charge_id)
    if recurring_charge.delete():
        messages.success(request, f"{recurring_charge.name} was successfully deleted")
    return redirect("recurring_charges")


@user_office_or_manager_required
@require_GET
def clear_recurring_charge(request, recurring_charge_id: int):
    recurring_charge = get_object_or_404(RecurringConsumableCharge, pk=recurring_charge_id)
    recurring_charge.clear()
    return redirect("recurring_charges")


def extended_permissions(request) -> bool:
    user: User = request.user
    lock_charges = RecurringChargesCustomization.get_bool("recurring_charges_lock")
    return not lock_charges or user.is_facility_manager or user.is_superuser


def make_withdrawal(
    consumable_id: int, quantity: int, project_id: int, merchant: User, customer_id: int, usage_event=None, request=None
):
    withdraw = ConsumableWithdraw(
        consumable_id=consumable_id,
        quantity=quantity,
        merchant=merchant,
        customer_id=customer_id,
        project_id=project_id,
        usage_event=usage_event,
    )
    withdraw.full_clean()
    withdraw.save()
    if not withdraw.consumable.reusable:
        # Only withdraw if it's an actual consumable (not reusable)
        withdraw.consumable.quantity -= withdraw.quantity
    withdraw.consumable.save()
    # Only add notification message if request is present
    if request:
        if request.user.id == customer_id:
            message = f"Your withdrawal of {withdraw.quantity} of {withdraw.consumable}"
        else:
            message = f"The withdrawal of {withdraw.quantity} of {withdraw.consumable} for {withdraw.customer}"
        message += f" was successfully logged and will be billed to project {withdraw.project}."
        messages.success(request, message, extra_tags="data-speed=9000")


def send_reorder_supply_reminder_email(consumable: Consumable):
    user_office_email = EmailsCustomization.get("user_office_email_address")
    message = get_media_file_contents("reorder_supplies_reminder_email.html")
    if user_office_email and message:
        subject = f"Time to order more {consumable.name}"
        rendered_message = render_email_template(message, {"item": consumable})
        send_mail(
            subject=subject,
            content=rendered_message,
            from_email=user_office_email,
            to=[consumable.reminder_email],
            email_category=EmailCategory.SYSTEM,
        )
