from datetime import datetime
from typing import List

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpResponseBadRequest, HttpResponseForbidden, QueryDict
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from NEMO.decorators import accounting_or_manager_required, accounting_or_user_office_or_manager_required
from NEMO.forms import AccountForm, ProjectForm
from NEMO.models import (
    Account,
    AccountType,
    ActivityHistory,
    AreaAccessRecord,
    ConsumableWithdraw,
    MembershipHistory,
    Project,
    ProjectDocuments,
    Reservation,
    StaffCharge,
    TrainingSession,
    UsageEvent,
    User,
)
from NEMO.utilities import date_input_format, queryset_search_filter
from NEMO.views.api_billing import BillableItem, BillingFilterForm, get_billing_charges
from NEMO.views.customization import ProjectsAccountsCustomization
from NEMO.views.pagination import SortedPaginator


class ProjectTransferForm(BillingFilterForm):
    end = forms.DateField(required=False)
    project_id = forms.IntegerField(required=True)
    new_project_id = forms.IntegerField(required=False)
    user_id = forms.IntegerField(required=False)

    def clean(self):
        errors = {}
        project_id = self.cleaned_data.get("project_id")
        new_project_id = self.cleaned_data.get("new_project_id")
        start = self.cleaned_data.get("start")
        end = self.cleaned_data.get("end")
        if project_id and project_id == new_project_id:
            errors["project_id"] = _("The projects have to be different")
            errors["new_project_id"] = _("The projects have to be different")
        if end and end < start:
            errors["end"] = _("The end date must be on or after the start date")
        if errors:
            raise ValidationError(errors)
        return self.cleaned_data


@accounting_or_user_office_or_manager_required
@require_GET
def accounts_and_projects(request):
    active_only = ProjectsAccountsCustomization.get_bool("account_list_active_only")
    all_accounts = Account.objects.all().order_by("name").prefetch_related("project_set")
    if active_only:
        all_accounts = all_accounts.filter(active=True)

    page = SortedPaginator(all_accounts, request, order_by="name").get_current_page()

    dictionary = {
        "page": page,
        "account_types": AccountType.objects.all(),
        "accounts_and_projects": get_accounts_and_projects(),
        "project_list_active_only": ProjectsAccountsCustomization.get_bool("project_list_active_only"),
        "account_list_collapse": ProjectsAccountsCustomization.get_bool("account_list_collapse"),
    }
    return render(request, "accounts_and_projects/accounts_and_projects.html", dictionary)


@accounting_or_user_office_or_manager_required
@require_GET
def select_accounts_and_projects(request, kind=None, identifier=None):
    selected_project = None
    try:
        if kind == "project":
            selected_project = Project.objects.get(id=identifier)
            account = selected_project.account
        elif kind == "account":
            account = Account.objects.get(id=identifier)
        else:
            account = None
    except:
        account = None
    account_projects = []
    if account:
        active_only = ProjectsAccountsCustomization.get_bool("account_project_list_active_only")
        account_projects = account.sorted_active_projects() if active_only else account.sorted_projects()
    dictionary = {
        "account": account,
        "account_projects": account_projects,
        "selected_project": selected_project,
        "accounts_and_projects": set(get_accounts_and_projects()),
        "users": User.objects.all(),
        "allow_document_upload": ProjectsAccountsCustomization.get_bool("project_allow_document_upload"),
    }
    return render(request, "accounts_and_projects/account_and_projects.html", dictionary)


@accounting_or_user_office_or_manager_required
@require_POST
def toggle_active(request, kind, identifier):
    if kind == "account":
        entity = get_object_or_404(Account, id=identifier)
    elif kind == "project":
        entity = get_object_or_404(Project, id=identifier)
    else:
        return HttpResponseBadRequest("Invalid entity for active toggle request.")
    entity.active = not entity.active
    entity.save()
    history = ActivityHistory()
    history.authorizer = request.user
    history.action = entity.active
    history.content_object = entity
    history.save()
    return redirect(request.META.get("HTTP_REFERER", "accounts_and_projects"))


@accounting_or_user_office_or_manager_required
@require_http_methods(["GET", "POST"])
def create_project(request):
    form = ProjectForm(request.POST or None)
    dictionary = {
        "account_list": Account.objects.all(),
        "user_list": User.objects.filter(is_active=True),
        "allow_document_upload": ProjectsAccountsCustomization.get_bool("project_allow_document_upload"),
        "form": form,
    }
    if request.method == "GET":
        return render(request, "accounts_and_projects/create_project.html", dictionary)
    if not form.is_valid():
        if request.FILES.getlist("project_documents") or request.POST.get("remove_documents"):
            form.add_error(field=None, error="Project document changes were lost, please resubmit them.")
        return render(request, "accounts_and_projects/create_project.html", dictionary)
    else:
        project = form.save()
        for f in request.FILES.getlist("project_documents"):
            ProjectDocuments.objects.create(document=f, project=project)
        account_history = MembershipHistory()
        account_history.authorizer = request.user
        account_history.action = MembershipHistory.Action.ADDED
        account_history.child_content_object = project
        account_history.parent_content_object = project.account
        account_history.save()
        project_history = ActivityHistory()
        project_history.authorizer = request.user
        project_history.action = project.active
        project_history.content_object = project
        project_history.save()
        return redirect("project", project.id)


@accounting_or_user_office_or_manager_required
@require_http_methods(["GET", "POST"])
def create_account(request):
    form = AccountForm(request.POST or None)
    dictionary = {"form": form}
    if request.method == "GET":
        return render(request, "accounts_and_projects/create_account.html", dictionary)
    if not form.is_valid():
        return render(request, "accounts_and_projects/create_account.html", dictionary)
    account = form.save()
    history = ActivityHistory()
    history.authorizer = request.user
    history.action = account.active
    history.content_object = account
    history.save()
    return redirect("account", account.id)


@require_POST
def remove_user_from_project(request):
    user = get_object_or_404(User, id=request.POST["user_id"])
    project = get_object_or_404(Project, id=request.POST["project_id"])
    if not is_user_allowed(request.user, project):
        return HttpResponseForbidden()
    if project.user_set.filter(id=user.id).exists():
        history = MembershipHistory()
        history.action = MembershipHistory.Action.REMOVED
        history.authorizer = request.user
        history.parent_content_object = project
        history.child_content_object = user
        history.save()
        project.user_set.remove(user)
    dictionary = {"users": project.user_set.all(), "project": project}
    return render(request, "accounts_and_projects/users_for_project.html", dictionary)


@require_POST
def add_user_to_project(request):
    user = get_object_or_404(User, id=request.POST["user_id"])
    project = get_object_or_404(Project, id=request.POST["project_id"])
    if not is_user_allowed(request.user, project):
        return HttpResponseForbidden()
    if user not in project.user_set.all():
        history = MembershipHistory()
        history.action = MembershipHistory.Action.ADDED
        history.authorizer = request.user
        history.parent_content_object = project
        history.child_content_object = user
        history.save()
        project.user_set.add(user)
    dictionary = {"users": project.user_set.all(), "project": project}
    return render(request, "accounts_and_projects/users_for_project.html", dictionary)


@accounting_or_user_office_or_manager_required
@require_POST
def remove_document_from_project(request, project_id: int, document_id: int):
    document = get_object_or_404(ProjectDocuments, pk=document_id)
    project = get_object_or_404(Project, id=project_id)
    document.delete()
    dictionary = {
        "documents": project.project_documents.all(),
        "project": project,
        "allow_document_upload": ProjectsAccountsCustomization.get_bool("project_allow_document_upload"),
    }
    return render(request, "accounts_and_projects/documents_for_project.html", dictionary)


@accounting_or_user_office_or_manager_required
@require_POST
def add_document_to_project(request, project_id: int):
    project = get_object_or_404(Project, id=project_id)
    for f in request.FILES.getlist("project_documents"):
        ProjectDocuments.objects.create(document=f, project=project)
    dictionary = {
        "documents": project.project_documents.all(),
        "project": project,
        "allow_document_upload": ProjectsAccountsCustomization.get_bool("project_allow_document_upload"),
    }
    return render(request, "accounts_and_projects/documents_for_project.html", dictionary)


@login_required
@require_GET
def projects(request):
    user: User = request.user
    dictionary = {"managed_projects": user.managed_projects.all(), "users": User.objects.all()}
    return render(request, "accounts_and_projects/projects.html", dictionary)


def is_user_allowed(user: User, project):
    is_active = user.is_active
    accounting_or_user_office_or_manager = (
        user.is_accounting_officer or user.is_user_office or user.is_facility_manager or user.is_superuser
    )
    allow_pi_manage = ProjectsAccountsCustomization.get_bool("project_allow_pi_manage_users")
    if not allow_pi_manage:
        return is_active and accounting_or_user_office_or_manager
    else:
        project_manager = user in project.manager_set.all()
        return is_active and (project_manager or accounting_or_user_office_or_manager)


@accounting_or_manager_required
@require_http_methods(["GET", "POST"])
def transfer_charges(request):
    if not ProjectsAccountsCustomization.get_bool("project_allow_transferring_charges"):
        return redirect("landing")
    form = ProjectTransferForm(request.POST or None)
    project = None
    new_project = None
    customer = None

    dictionary = {}
    if request.method == "POST":
        if form.is_valid():
            project = Project.objects.filter(pk=form.cleaned_data.get("project_id")).first()
            new_project_id = form.cleaned_data.get("new_project_id")
            user_id = form.cleaned_data.get("user_id")
            if new_project_id:
                new_project = Project.objects.filter(pk=new_project_id).first()
            if user_id:
                customer = User.objects.filter(id=user_id).first()
            charges = get_charges_for_project_and_user(request.POST, customer.username if customer else None)
            confirm = "confirm" in request.POST
            if confirm:
                if not new_project_id:
                    dictionary["charges"] = charges
                    form.add_error("new_project_id", _("This field is required"))
                else:
                    do_transfer_charges(charges, new_project.id)
                    messages.success(
                        request,
                        f"{len(charges)} charges were transferred from {project} to {new_project}",
                        extra_tags="data-speed=25000",
                    )
            else:
                dictionary["charges"] = charges
    dictionary.update({"form": form, "project": project, "new_project": new_project, "customer": customer})
    return render(request, "accounts_and_projects/transfer_charges.html", dictionary)


def get_charges_for_project_and_user(params: QueryDict, username: str = None) -> List[BillableItem]:
    dictionary = params.copy()
    dictionary["username"] = username
    if not dictionary.get("end"):
        dictionary["end"] = datetime.now().strftime(date_input_format)
    return get_billing_charges(dictionary)


@transaction.atomic
def do_transfer_charges(charges: List[BillableItem], new_project_id: int):
    usage_event_ids = []
    area_access_record_ids = []
    consumable_withdrawal_ids = []
    missed_reservation_ids = []
    staff_charge_ids = []
    training_session_ids = []
    for charge in charges:
        if charge.type == "tool_usage":
            usage_event_ids.append(charge.item_id)
        elif charge.type == "area_access":
            area_access_record_ids.append(charge.item_id)
        elif charge.type == "consumable":
            consumable_withdrawal_ids.append(charge.item_id)
        elif charge.type == "missed_reservation":
            missed_reservation_ids.append(charge.item_id)
        elif charge.type == "staff_charge":
            staff_charge_ids.append(charge.item_id)
        elif charge.type == "training_session":
            training_session_ids.append(charge.item_id)
    UsageEvent.objects.filter(id__in=usage_event_ids).update(project_id=new_project_id)
    AreaAccessRecord.objects.filter(id__in=area_access_record_ids).update(project_id=new_project_id)
    ConsumableWithdraw.objects.filter(id__in=consumable_withdrawal_ids).update(project_id=new_project_id)
    Reservation.objects.filter(id__in=missed_reservation_ids).update(project_id=new_project_id)
    StaffCharge.objects.filter(id__in=staff_charge_ids).update(project_id=new_project_id)
    TrainingSession.objects.filter(id__in=training_session_ids).update(project_id=new_project_id)


@accounting_or_manager_required
@require_GET
def search_project_for_transfer(request):
    return queryset_search_filter(Project.objects.all(), ["name", "application_identifier"], request)


def get_accounts_and_projects():
    items = set(Account.objects.all()) | set(Project.objects.all())
    return sorted(items, key=lambda x: (-x.active, x.name.lower()))
