from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from NEMO.decorators import accounting_or_user_office_or_manager_required
from NEMO.forms import AccountForm, ProjectForm
from NEMO.models import Account, AccountType, ActivityHistory, MembershipHistory, Project, ProjectDocuments, User
from NEMO.views.customization import ProjectsAccountsCustomization
from NEMO.views.pagination import SortedPaginator


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
        "accounts_and_projects": set(Account.objects.all()) | set(Project.objects.all()),
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
    dictionary = {
        "account": account,
        "selected_project": selected_project,
        "accounts_and_projects": set(Account.objects.all()) | set(Project.objects.all()),
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
