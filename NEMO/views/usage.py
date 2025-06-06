from collections import defaultdict
from logging import getLogger
from typing import Callable, List, Set

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db.models import F, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET
from requests import get

from NEMO.decorators import accounting_or_user_office_or_manager_required, any_staff_required
from NEMO.models import (
    Account,
    AccountType,
    AdjustmentRequest,
    AreaAccessRecord,
    ConsumableWithdraw,
    Project,
    ProjectType,
    Reservation,
    StaffCharge,
    TrainingSession,
    UsageEvent,
    User,
)
from NEMO.utilities import (
    BasicDisplayTable,
    export_format_datetime,
    extract_optional_beginning_and_end_dates,
    get_day_timeframe,
    get_month_timeframe,
    month_list,
)
from NEMO.views.api_billing import (
    BillableItem,
    billable_items_area_access_records,
    billable_items_consumable_withdrawals,
    billable_items_missed_reservations,
    billable_items_staff_charges,
    billable_items_training_sessions,
    billable_items_usage_events,
)
from NEMO.views.customization import AdjustmentRequestsCustomization, ProjectsAccountsCustomization

logger = getLogger(__name__)


# Class for Applications that can be used for autocomplete
class Application(object):
    def __init__(self, name):
        self.name = name
        self.id = name

    def __str__(self):
        return self.name


def get_project_applications():
    applications = []
    projects = Project.objects.filter(
        id__in=Project.objects.values("application_identifier").distinct().values_list("id", flat=True)
    )
    for project in projects:
        if not any(list(filter(lambda app: app.name == project.application_identifier, applications))):
            applications.append(Application(project.application_identifier))
    return applications


def date_parameters_dictionary(request, default_function: Callable = get_month_timeframe):
    if request.GET.get("start") and request.GET.get("end"):
        start_date, end_date = extract_optional_beginning_and_end_dates(request.GET, date_only=True)
    else:
        start_date, end_date = default_function()
    kind = request.GET.get("type")
    identifier = request.GET.get("id")
    existing_adjustments = defaultdict(list)
    for values in (
        AdjustmentRequest.objects.filter(deleted=False, creator=request.user).values("item_type", "item_id").distinct()
    ):
        existing_adjustments[values["item_type"]].append(values["item_id"])
    title = ""
    if reverse("staff_usage") in request.get_full_path():
        title += "staff "
    elif reverse("project_usage") in request.get_full_path() or reverse("project_billing") in request.get_full_path():
        title += "facility "
    if reverse("billing") in request.get_full_path() or reverse("project_billing") in request.get_full_path():
        title += "billing"
    else:
        title += "usage"
    dictionary = {
        "month_list": month_list(),
        "start_date": start_date,
        "end_date": end_date,
        "kind": kind,
        "identifier": identifier,
        "title": title.capitalize(),
        "explicitly_display_customer": reverse("user_usage") not in request.get_full_path(),
        "billing_service": get_billing_service().get("available", False),
        "adjustment_time_limit": AdjustmentRequestsCustomization.get_date_limit(),
        "existing_adjustments": existing_adjustments,
    }
    return dictionary, start_date, end_date, kind, identifier


@login_required
@require_GET
def user_usage(request):
    user: User = request.user
    user_managed_projects = get_managed_projects(user)
    customer_filter = Q(customer=user) | Q(project__in=user_managed_projects)
    user_filter = Q(user=user) | Q(project__in=user_managed_projects)
    trainee_filter = Q(trainee=user) | Q(project__in=user_managed_projects)
    show_only_my_usage = user_managed_projects and request.GET.get("show_only_my_usage", "enabled") == "enabled"
    csv_export = bool(request.GET.get("csv", False))
    if show_only_my_usage:
        # Forcing to be user only
        customer_filter &= Q(customer=user)
        user_filter &= Q(user=user)
        trainee_filter &= Q(trainee=user)
        csv_export = bool(request.GET.get("csv", False))
    return usage(
        request,
        usage_filter=user_filter,
        area_access_filter=customer_filter,
        staff_charges_filter=customer_filter,
        consumable_filter=customer_filter,
        reservation_filter=user_filter,
        training_filter=trainee_filter,
        show_only_my_usage=show_only_my_usage,
        csv_export=csv_export,
        user_managed_projects=user_managed_projects,
    )


@any_staff_required
@require_GET
def staff_usage(request):
    user: User = request.user
    usage_filter = Q(operator=user) & ~Q(user=F("operator"))
    area_access_filter = Q(staff_charge__staff_member=user)
    staff_charges_filter = Q(staff_member=user)
    consumable_filter = Q(merchant=user)
    user_filter = Q(pk__in=[])
    trainee_filter = Q(trainer=user)
    csv_export = bool(request.GET.get("csv", False))
    return usage(
        request,
        usage_filter=usage_filter,
        area_access_filter=area_access_filter,
        staff_charges_filter=staff_charges_filter,
        consumable_filter=consumable_filter,
        reservation_filter=user_filter,
        training_filter=trainee_filter,
        show_only_my_usage=None,
        csv_export=csv_export,
        user_managed_projects=set(),
    )


def usage(
    request,
    usage_filter,
    area_access_filter,
    staff_charges_filter,
    consumable_filter,
    reservation_filter,
    training_filter,
    show_only_my_usage,
    csv_export,
    user_managed_projects,
):
    user: User = request.user
    base_dictionary, start_date, end_date, kind, identifier = date_parameters_dictionary(request, get_month_timeframe)
    project_id = request.GET.get("project") or request.GET.get("pi_project")
    if user_managed_projects:
        base_dictionary["selected_project"] = "all"
    if project_id:
        project = get_object_or_404(Project, id=project_id)
        if request.GET.get("project"):
            base_dictionary["selected_user_project"] = project
        else:
            base_dictionary["selected_project"] = project
            base_dictionary["explicitly_display_customer"] = True
        area_access_filter &= Q(project=project)
        staff_charges_filter &= Q(project=project)
        usage_filter &= Q(project=project)
        consumable_filter &= Q(project=project)
        reservation_filter &= Q(project=project)
        training_filter &= Q(project=project)
    area_access = (
        AreaAccessRecord.objects.filter(area_access_filter)
        .filter(end__gt=start_date, end__lte=end_date)
        .order_by("-start")
    )
    consumables = ConsumableWithdraw.objects.filter(consumable_filter).filter(date__gt=start_date, date__lte=end_date)
    missed_reservations = Reservation.objects.filter(reservation_filter).filter(
        missed=True, end__gt=start_date, end__lte=end_date
    )
    staff_charges = StaffCharge.objects.filter(staff_charges_filter).filter(end__gt=start_date, end__lte=end_date)
    training_sessions = TrainingSession.objects.filter(training_filter).filter(date__gt=start_date, date__lte=end_date)
    usage_events = UsageEvent.objects.filter(usage_filter).filter(end__gt=start_date, end__lte=end_date)
    if csv_export:
        return csv_export_response(
            user, usage_events, area_access, training_sessions, staff_charges, consumables, missed_reservations
        )
    else:
        dictionary = {
            "area_access": area_access,
            "consumables": consumables,
            "missed_reservations": missed_reservations,
            "staff_charges": staff_charges,
            "training_sessions": training_sessions,
            "usage_events": usage_events,
            "charges_projects": Project.objects.filter(
                id__in=set(
                    list(user.active_projects().values_list("id", flat=True))
                    + list(usage_events.values_list("project", flat=True))
                    + list(area_access.values_list("project", flat=True))
                    + list(missed_reservations.values_list("project", flat=True))
                    + list(consumables.values_list("project", flat=True))
                    + list(staff_charges.values_list("project", flat=True))
                    + list(training_sessions.values_list("project", flat=True))
                )
            ),
        }
        if user_managed_projects:
            dictionary["pi_projects"] = user_managed_projects
            dictionary["show_only_my_usage"] = show_only_my_usage
        dictionary["no_charges"] = not (
            dictionary["area_access"]
            or dictionary["consumables"]
            or dictionary["missed_reservations"]
            or dictionary["staff_charges"]
            or dictionary["training_sessions"]
            or dictionary["usage_events"]
        )
        return render(request, "usage/usage.html", {**base_dictionary, **dictionary})


@login_required
@require_GET
def billing(request):
    user: User = request.user
    base_dictionary, start_date, end_date, kind, identifier = date_parameters_dictionary(request, get_month_timeframe)
    if not base_dictionary["billing_service"]:
        return redirect("user_usage")
    user_project_applications = list(user.active_projects().values_list("application_identifier", flat=True)) + list(
        user.managed_projects.values_list("application_identifier", flat=True)
    )
    formatted_applications = ",".join(map(str, set(user_project_applications)))
    try:
        billing_dictionary = billing_dict(start_date, end_date, user, formatted_applications)
        return render(request, "usage/billing.html", {**base_dictionary, **billing_dictionary})
    except Exception as e:
        logger.warning(str(e))
        return render(request, "usage/billing.html", base_dictionary)


@accounting_or_user_office_or_manager_required
@require_GET
def project_usage(request):
    base_dictionary, start_date, end_date, kind, identifier = date_parameters_dictionary(request, get_day_timeframe)

    area_access, consumables, missed_reservations, staff_charges, training_sessions, usage_events = (
        None,
        None,
        None,
        None,
        None,
        None,
    )

    projects = []
    user = None
    selection = ""

    # Get selection as strings.
    selected_account_type = request.GET.get("account_type", None)
    selected_project_type = request.GET.get("project_type", None)

    # Convert to int for id comparison.
    selected_account_type = int(selected_account_type) if selected_account_type else None
    selected_project_type = int(selected_project_type) if selected_project_type else None

    try:
        if kind == "application":
            projects = Project.objects.filter(application_identifier=identifier)
            selection = identifier
        elif kind == "project":
            projects = [Project.objects.get(id=identifier)]
            selection = projects[0].name
        elif kind == "account":
            account = Account.objects.get(id=identifier)
            projects = Project.objects.filter(account=account)
            selection = account.name
        elif kind == "user":
            user = User.objects.get(id=identifier)
            projects = user.active_projects()
            selection = str(user)

        area_access = AreaAccessRecord.objects.filter(end__gt=start_date, end__lte=end_date).order_by("-start")
        consumables = ConsumableWithdraw.objects.filter(date__gt=start_date, date__lte=end_date)
        missed_reservations = Reservation.objects.filter(missed=True, end__gt=start_date, end__lte=end_date)
        staff_charges = StaffCharge.objects.filter(end__gt=start_date, end__lte=end_date)
        training_sessions = TrainingSession.objects.filter(date__gt=start_date, date__lte=end_date)
        usage_events = UsageEvent.objects.filter(end__gt=start_date, end__lte=end_date)
        if projects:
            area_access = area_access.filter(project__in=projects)
            consumables = consumables.filter(project__in=projects)
            missed_reservations = missed_reservations.filter(project__in=projects)
            staff_charges = staff_charges.filter(project__in=projects)
            training_sessions = training_sessions.filter(project__in=projects)
            usage_events = usage_events.filter(project__in=projects)
        if user:
            area_access = area_access.filter(customer=user)
            consumables = consumables.filter(customer=user)
            missed_reservations = missed_reservations.filter(user=user)
            staff_charges = staff_charges.filter(customer=user)
            training_sessions = training_sessions.filter(trainee=user)
            usage_events = usage_events.filter(user=user)
        if selected_account_type:
            # Get a subset of projects and filter the other records using that subset.
            projects_by_account_type = Project.objects.filter(account__type__id=selected_account_type)
            area_access = area_access.filter(project__in=projects_by_account_type)
            consumables = consumables.filter(project__in=projects_by_account_type)
            missed_reservations = missed_reservations.filter(project__in=projects_by_account_type)
            staff_charges = staff_charges.filter(project__in=projects_by_account_type)
            training_sessions = training_sessions.filter(project__in=projects_by_account_type)
            usage_events = usage_events.filter(project__in=projects_by_account_type)
        if selected_project_type:
            # Get a subset of projects and filter the other records using that subset.
            projects_by_type = Project.objects.filter(project_types__id=selected_project_type)
            area_access = area_access.filter(project__in=projects_by_type)
            consumables = consumables.filter(project__in=projects_by_type)
            missed_reservations = missed_reservations.filter(project__in=projects_by_type)
            staff_charges = staff_charges.filter(project__in=projects_by_type)
            training_sessions = training_sessions.filter(project__in=projects_by_type)
            usage_events = usage_events.filter(project__in=projects_by_type)
        if bool(request.GET.get("csv", False)):
            return csv_export_response(
                request.user,
                usage_events,
                area_access,
                training_sessions,
                staff_charges,
                consumables,
                missed_reservations,
            )
    except:
        pass

    # Get a list of unique account types for the dropdown field.
    account_types = AccountType.objects.filter(id__in=Account.objects.values_list('type__id', flat=True))

    # Get a list of unique project types for the dropdown field.
    project_types = ProjectType.objects.filter(id__in=Project.objects.values_list('project_types__id', flat=True))

    dictionary = {
        "search_items": set(Account.objects.all())
        | set(Project.objects.all())
        | set(get_project_applications())
        | set(User.objects.all()),
        "area_access": area_access,
        "consumables": consumables,
        "missed_reservations": missed_reservations,
        "staff_charges": staff_charges,
        "training_sessions": training_sessions,
        "usage_events": usage_events,
        "project_autocomplete": True,
        "selection": selection,
        "account_types": account_types,
        "selected_account_type": selected_account_type,
        "project_types": project_types,
        "selected_project_type": selected_project_type,
    }
    dictionary["no_charges"] = not (
        dictionary["area_access"]
        or dictionary["consumables"]
        or dictionary["missed_reservations"]
        or dictionary["staff_charges"]
        or dictionary["training_sessions"]
        or dictionary["usage_events"]
    )
    return render(request, "usage/usage.html", {**base_dictionary, **dictionary})


@accounting_or_user_office_or_manager_required
@require_GET
def project_billing(request):
    base_dictionary, start_date, end_date, kind, identifier = date_parameters_dictionary(request, get_day_timeframe)
    if not base_dictionary["billing_service"]:
        return redirect("project_usage")
    base_dictionary["project_autocomplete"] = True
    base_dictionary["search_items"] = (
        set(Account.objects.all())
        | set(Project.objects.all())
        | set(get_project_applications())
        | set(User.objects.all())
    )

    project_id = None
    account_id = None
    user = None
    formatted_applications = None
    selection = ""
    try:
        if kind == "application":
            formatted_applications = identifier
            selection = identifier
        elif kind == "project":
            projects = [Project.objects.get(id=identifier)]
            formatted_applications = projects[0].application_identifier
            project_id = identifier
            selection = projects[0].name
        elif kind == "account":
            account = Account.objects.get(id=identifier)
            projects = Project.objects.filter(account=account, active=True, account__active=True)
            formatted_applications = (
                ",".join(map(str, set(projects.values_list("application_identifier", flat=True)))) if projects else None
            )
            account_id = account.id
            selection = account.name
        elif kind == "user":
            user = User.objects.get(id=identifier)
            projects = user.active_projects()
            formatted_applications = (
                ",".join(map(str, set(projects.values_list("application_identifier", flat=True)))) if projects else None
            )
            selection = str(user)

        base_dictionary["selection"] = selection
        billing_dictionary = billing_dict(
            start_date,
            end_date,
            user,
            formatted_applications,
            project_id,
            account_id=account_id,
            force_pi=True if not user else False,
        )
        return render(request, "usage/billing.html", {**base_dictionary, **billing_dictionary})
    except Exception as e:
        logger.warning(str(e))
        return render(request, "usage/billing.html", base_dictionary)


def is_user_pi(user: User, latest_pis_data, activity, user_managed_applications: List[str]):
    # Check if the user is set as a PI in NEMO, otherwise check from latest_pis_data
    application = activity["application_name"]
    if application in user_managed_applications:
        return True
    else:
        application_pi_row = next((x for x in latest_pis_data if x["application_name"] == application), None)
        return application_pi_row is not None and (
            user.username == application_pi_row["username"]
            or (
                user.first_name == application_pi_row["first_name"]
                and user.last_name == application_pi_row["last_name"]
            )
        )


def billing_dict(start_date, end_date, user, formatted_applications, project_id=None, account_id=None, force_pi=False):
    # The parameter force_pi allows us to display information as if the user was the project pi
    # This is useful on the admin project billing page tp display other project users for example
    dictionary = {}

    billing_service = get_billing_service()
    if not billing_service.get("available", False):
        return dictionary

    cost_activity_url = billing_service["cost_activity_url"]
    project_lead_url = billing_service["project_lead_url"]
    keyword_arguments = billing_service["keyword_arguments"]

    cost_activity_params = {
        "created_date_gte": f"'{start_date.strftime('%m/%d/%Y')}'",
        "created_date_lt": f"'{end_date.strftime('%m/%d/%Y')}'",
        "application_names": f"'{formatted_applications}'",
        "$format": "json",
    }
    cost_activity_response = get(cost_activity_url, params=cost_activity_params, **keyword_arguments)
    cost_activity_data = cost_activity_response.json()["d"]

    if not force_pi:
        latest_pis_params = {"$format": "json"}
        latest_pis_response = get(project_lead_url, params=latest_pis_params, **keyword_arguments)
        latest_pis_data = latest_pis_response.json()["d"]

    project_totals = {}
    application_totals = {}
    account_totals = {}
    user_pi_applications = list()
    # Construct a tree of account, application, project, and member total spending
    cost_activities_tree = {}
    user_managed_applications = (
        [project.application_identifier for project in user.managed_projects.all()] if not force_pi else []
    )
    for activity in cost_activity_data:
        if (project_id and activity["project_id"] != str(project_id)) or (
            account_id and activity["account_id"] != str(account_id)
        ):
            continue
        project_totals.setdefault(activity["project_id"], 0)
        application_totals.setdefault(activity["application_id"], 0)
        account_totals.setdefault(activity["account_id"], 0)
        account_key = (activity["account_id"], activity["account_name"])
        application_key = (activity["application_id"], activity["application_name"])
        project_key = (activity["project_id"], activity["project_name"])
        user_key = (activity["member_id"], User.objects.filter(id__in=[activity["member_id"]]).first())
        user_is_pi = is_user_pi(user, latest_pis_data, activity, user_managed_applications) if not force_pi else True
        if user_is_pi:
            user_pi_applications.append(activity["application_id"])
        if user_is_pi or str(user.id) == activity["member_id"]:
            cost_activities_tree.setdefault((activity["account_id"], activity["account_name"]), {})
            cost_activities_tree[account_key].setdefault(application_key, {})
            cost_activities_tree[account_key][application_key].setdefault(project_key, {})
            cost_activities_tree[account_key][application_key][project_key].setdefault(user_key, 0)
            cost = 0
            if activity["cost"] is not None:
                cost = -activity["cost"] if activity["activity_type"] == "refund_activity" else activity["cost"]
            cost_activities_tree[account_key][application_key][project_key][user_key] = (
                cost_activities_tree[account_key][application_key][project_key][user_key] + cost
            )
            project_totals[activity["project_id"]] = project_totals[activity["project_id"]] + cost
            application_totals[activity["application_id"]] = application_totals[activity["application_id"]] + cost
            account_totals[activity["account_id"]] = account_totals[activity["account_id"]] + cost
    dictionary["spending"] = (
        {
            "activities": cost_activities_tree,
            "project_totals": project_totals,
            "application_totals": application_totals,
            "account_totals": account_totals,
            "user_pi_applications": user_pi_applications,
        }
        if cost_activities_tree
        else {"activities": {}}
    )
    return dictionary


def csv_export_response(
    user: User, usage_events, area_access, training_sessions, staff_charges, consumables, missed_reservations
):
    table_result = BasicDisplayTable()
    table_result.add_header(("type", "Type"))
    table_result.add_header(("user", "User"))
    table_result.add_header(("name", "Item"))
    table_result.add_header(("details", "Details"))
    table_result.add_header(("project", "Project"))
    if user.is_any_part_of_staff:
        table_result.add_header(
            ("application", ProjectsAccountsCustomization.get("project_application_identifier_name"))
        )
    table_result.add_header(("start", "Start time"))
    table_result.add_header(("end", "End time"))
    table_result.add_header(("quantity", "Quantity"))
    data: List[BillableItem] = []
    data.extend(billable_items_missed_reservations(missed_reservations))
    data.extend(billable_items_consumable_withdrawals(consumables))
    data.extend(billable_items_staff_charges(staff_charges))
    data.extend(billable_items_training_sessions(training_sessions))
    data.extend(billable_items_area_access_records(area_access))
    data.extend(billable_items_usage_events(usage_events))
    for billable_item in data:
        table_result.add_row(vars(billable_item))
    response = table_result.to_csv()
    filename = f"usage_export_{export_format_datetime()}.csv"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def get_managed_projects(user: User) -> Set[Project]:
    # This function will get managed projects from NEMO and also attempt to get them from billing service
    managed_projects = set(list(user.managed_projects.all()))
    billing_service = get_billing_service()
    if billing_service.get("available", False):
        # if we have a billing service, use it to determine project lead
        try:
            project_lead_url = billing_service["project_lead_url"]
            keyword_arguments = billing_service["keyword_arguments"]
            latest_pis_params = {"$format": "json"}
            latest_pis_response = get(project_lead_url, params=latest_pis_params, **keyword_arguments)
            latest_pis_data = latest_pis_response.json()["d"]
            for project_lead in latest_pis_data:
                if project_lead["username"] == user.username or (
                    project_lead["first_name"] == user.first_name and project_lead["last_name"] == user.last_name
                ):
                    try:
                        for managed_project in Project.objects.filter(
                            application_identifier=project_lead["application_name"]
                        ):
                            managed_projects.add(managed_project)
                    except Project.DoesNotExist:
                        pass
        except Exception:
            logger.exception("error loading project leads from billing service")
    return managed_projects


def get_billing_service():
    return getattr(settings, "BILLING_SERVICE", {})
