from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest
from django.shortcuts import render, get_object_or_404, redirect
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from NEMO.forms import ProjectForm, AccountForm
from NEMO.models import Account, Project, User, MembershipHistory, ActivityHistory
from NEMO.views.pagination import SortedPaginator


@staff_member_required(login_url=None)
@require_GET
def accounts_and_projects(request):
	all_accounts = Account.objects.all().order_by("name")

	page = SortedPaginator(all_accounts, request, order_by="name").get_current_page()

	dictionary = {"page": page, "accounts_and_projects": set(Account.objects.all()) | set(Project.objects.all())}
	return render(request, "accounts_and_projects/accounts_and_projects.html", dictionary)


@staff_member_required(login_url=None)
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
	}
	return render(request, "accounts_and_projects/account_and_projects.html", dictionary)


@staff_member_required(login_url=None)
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


@staff_member_required(login_url=None)
@require_http_methods(["GET", "POST"])
def create_project(request):
	form = ProjectForm(request.POST or None)
	dictionary = {"account_list": Account.objects.all(), "user_list": User.objects.filter(is_active=True), "form": form}
	if request.method == "GET":
		return render(request, "accounts_and_projects/create_project.html", dictionary)
	if not form.is_valid():
		return render(request, "accounts_and_projects/create_project.html", dictionary)
	project = form.save()
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


@staff_member_required(login_url=None)
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


@staff_member_required(login_url=None)
@require_POST
def remove_user_from_project(request):
	user = get_object_or_404(User, id=request.POST["user_id"])
	project = get_object_or_404(Project, id=request.POST["project_id"])
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


@staff_member_required(login_url=None)
@require_POST
def add_user_to_project(request):
	user = get_object_or_404(User, id=request.POST["user_id"])
	project = get_object_or_404(Project, id=request.POST["project_id"])
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


@login_required
@require_GET
def projects(request):
	user: User = request.user
	dictionary = {"managed_projects": user.managed_projects.all()}
	return render(request, "accounts_and_projects/projects.html", dictionary)
