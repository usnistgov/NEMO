from datetime import timedelta
from logging import getLogger
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Max
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from NEMO.decorators import any_staff_required, user_office_or_manager_required
from NEMO.forms import UserForm, UserPreferencesForm
from NEMO.models import (
    ActivityHistory,
    Area,
    AreaAccessRecord,
    OnboardingPhase,
    PhysicalAccessLevel,
    Project,
    Reservation,
    SafetyTraining,
    StaffCharge,
    Tool,
    UsageEvent,
    User,
    UserDocuments,
    UserType,
    record_active_state,
    record_local_many_to_many_changes,
)
from NEMO.identity_service import identity_service
from NEMO.utilities import queryset_search_filter
from NEMO.views.customization import ApplicationCustomization, StatusDashboardCustomization, UserCustomization
from NEMO.views.pagination import SortedPaginator
from NEMO.views.status_dashboard import show_staff_status

users_logger = getLogger(__name__)


@any_staff_required
@require_GET
def users(request):
    user_list = User.objects.all()
    only_active = UserCustomization.get_bool("user_list_active_only")
    if only_active:
        user_list = user_list.filter(is_active=True)
    page = SortedPaginator(user_list, request, order_by="last_name").get_current_page()

    dictionary = {"page": page, "user_types": UserType.objects.all(), "readonly": readonly_users(request)}

    return render(request, "users/users.html", dictionary)


@any_staff_required
@require_GET
def user_search(request):
    return queryset_search_filter(User.objects.all(), ["first_name", "last_name", "username"], request)


@any_staff_required
@require_http_methods(["GET", "POST"])
def create_or_modify_user(request, user_id):
    # Get access levels and sort by area category
    access_levels = list(PhysicalAccessLevel.objects.all().only("name", "area"))
    access_level_for_sort = list(
        set([ancestor for access in access_levels for ancestor in access.area.get_ancestors(include_self=True)])
    )
    access_level_for_sort.sort(key=lambda x: x.tree_category())
    area_access_levels = Area.objects.filter(id__in=[area.id for area in access_level_for_sort])
    dict_area = {}
    for access in access_levels:
        dict_area.setdefault(access.area.id, []).append(access)

    readonly = readonly_users(request)
    dictionary = {
        "projects": Project.objects.filter(active=True, account__active=True).prefetch_related("manager_set"),
        "tools": Tool.objects.filter(visible=True),
        "area_access_dict": dict_area,
        "area_access_levels": area_access_levels,
        "one_year_from_now": timezone.localdate() + timedelta(days=365),
        "identity_service_available": identity_service.available,
        "identity_service_domains": identity_service.domains,
        "allow_document_upload": UserCustomization.get_bool("user_allow_document_upload"),
        "readonly": readonly,
    }

    user = None
    if user_id != "new":
        user = (
            User.objects.filter(id=user_id).prefetch_related("projects__manager_set", "physical_access_levels").first()
        )

    last_access = AreaAccessRecord.objects.filter(customer=user).values("area_id").annotate(max_date=Max("start"))
    dictionary["last_access"] = {item["area_id"]: item["max_date"] for item in last_access}

    site_title = ApplicationCustomization.get("site_title")
    if identity_service.available:
        data, error = identity_service.get_externally_managed_areas()
        if data is not None:
            dictionary["externally_managed_physical_access_levels"] = data
        if error:
            dictionary["warning"] = error
        dictionary["identity_service_available"] = False
    elif identity_service.config:
        # display warning if identity service is defined but disabled
        dictionary["warning"] = (
            "The identity service is disabled. You will not be able to modify externally managed physical access levels, reset account passwords, or unlock accounts."
        )

    if readonly or request.method == "GET":
        training_not_required = UserCustomization.get_bool("default_user_training_not_required", raise_exception=False)
        inactive_by_default = UserCustomization.get_bool("default_user_is_inactive", raise_exception=False)
        # Only set training required initial value on new users
        initial_data = {}
        if not user:
            # set correlation id to be used later on when saving the user
            request.session["user_correlation_id"] = request.GET.get("correlation_id", "")
            initial_data: dict = {
                "training_required": not training_not_required,
                "is_active": not inactive_by_default,
                "first_name": request.GET.get("first_name", ""),
                "last_name": request.GET.get("last_name", ""),
                "email": request.GET.get("email", ""),
                "type": request.GET.get("type", ""),
                "notes": request.GET.get("notes", ""),
            }

        dictionary["form"] = UserForm(instance=user, initial=initial_data)
        if dictionary["identity_service_available"] and user and user.is_active and user.domain:
            data, error = identity_service.get_user_identity_information(user.username, user.domain)
            if data is not None:
                dictionary["user_identity_information"] = data
            if error:
                dictionary["warning"] = error
                if data is None:
                    dictionary["identity_service_available"] = False
        return render(request, "users/create_or_modify_user.html", dictionary)
    elif request.method == "POST":
        form = UserForm(request.POST, instance=user)
        dictionary["form"] = form
        if not form.is_valid():
            if request.FILES.getlist("user_documents") or request.POST.get("remove_documents"):
                form.add_error(field=None, error="User document changes were lost, please resubmit them.")
            return render(request, "users/create_or_modify_user.html", dictionary)

        # Remove the user account from the domain if it's deactivated, changed domain, or changed username...
        if dictionary["identity_service_available"] and user:
            no_longer_active = form.initial["is_active"] is True and form.cleaned_data["is_active"] is False
            domain_switched = form.initial["domain"] != "" and form.initial["domain"] != form.cleaned_data["domain"]
            username_changed = form.initial["username"] != form.cleaned_data["username"]
            if no_longer_active or domain_switched or username_changed:
                data, error = identity_service.delete_user(form.initial["username"], form.initial["domain"])
                if error:
                    dictionary["warning"] = error
                    dictionary["identity_service_available"] = False
                    return render(request, "users/create_or_modify_user.html", dictionary)

        # Ensure the user account is added and configured correctly on the current domain if the user is active...
        if dictionary["identity_service_available"] and form.cleaned_data["is_active"]:
            badge_number = form.cleaned_data.get("badge_number", "")
            email = form.cleaned_data.get("email")
            access_expiration = form.cleaned_data.get("access_expiration")
            requested_areas = request.POST.getlist("externally_managed_access_levels")
            if len(requested_areas) > 0 and not badge_number:
                dictionary["warning"] = (
                    "A user must have a badge number in order to have area access. Please enter the badge number first, then grant access to areas."
                )
                return render(request, "users/create_or_modify_user.html", dictionary)
            data, error = identity_service.update_user(
                form.cleaned_data["username"],
                form.cleaned_data["domain"],
                badge_number=badge_number,
                email=email,
                access_expiration=access_expiration,
                requested_areas=requested_areas,
            )
            if error:
                dictionary["warning"] = error
                if data is None:
                    dictionary["identity_service_available"] = False
                return render(request, "users/create_or_modify_user.html", dictionary)

        # Only save the user model for now, and wait to process the many-to-many relationships.
        # This way, many-to-many changes can be recorded.
        # See this web page for more information:
        # https://docs.djangoproject.com/en/dev/topics/forms/modelforms/#the-save-method
        user = form.save(commit=False)
        # Retrieve correlation ID from the session and set it on the new user.
        # This allows for plugins or other packages to find this user later in signals
        corr_id = request.session.get("user_correlation_id")
        if corr_id and user_id == "new":
            user._correlation_id = corr_id
        user.save()
        if "user_correlation_id" in request.session:
            del request.session["user_correlation_id"]
        record_active_state(request, user, form, "is_active", user_id == "new")

        record_qualifications(request.user, user, request.POST.getlist("qualifications", []))
        record_local_many_to_many_changes(request, user, form, "physical_access_levels")
        record_local_many_to_many_changes(request, user, form, "projects")
        form.save_m2m()

        # Handle file uploads
        for f in request.FILES.getlist("user_documents"):
            UserDocuments.objects.create(document=f, user=user)
        UserDocuments.objects.filter(id__in=request.POST.getlist("remove_documents")).delete()

        message = (
            f"{user} has been added successfully to {site_title}"
            if user_id == "new"
            else f"{user} has been updated successfully"
        )
        messages.success(request, message)
        redirect_view = request.GET.get("next")
        if redirect_view:
            return redirect(redirect_view)
        else:
            return redirect("view_user", user.id)
    else:
        return HttpResponseBadRequest("Invalid method")


def record_qualifications(request_user, user, qualifications: list[str]):
    from NEMO.views.qualifications import qualify, disqualify

    tools = set()
    if qualifications:
        for tool_id in qualifications:
            tool = Tool.objects.get(pk=tool_id)
            qualify(request_user, tool, user)
            tools.add(tool)
    for tool in set(user.qualifications.all()).difference(tools):
        disqualify(request_user, tool, user)


@user_office_or_manager_required
@require_http_methods(["GET", "POST"])
def deactivate(request, user_id):
    dictionary = {
        "user_to_deactivate": get_object_or_404(User, id=user_id),
        "reservations": Reservation.objects.filter(user=user_id, cancelled=False, missed=False, end__gt=timezone.now()),
        "staff_charges": StaffCharge.objects.filter(customer=user_id, end=None),
        "tool_usage": UsageEvent.objects.filter(user=user_id, end=None).prefetch_related("tool"),
    }
    user_to_deactivate = dictionary["user_to_deactivate"]
    if request.method == "GET":
        return render(request, "users/safe_deactivation.html", dictionary)
    elif request.method == "POST":
        if identity_service.available:
            data, error = identity_service.delete_user(user_to_deactivate.username, user_to_deactivate.domain)
            if error:
                dictionary["warning"] = error
                return render(request, "users/safe_deactivation.html", dictionary)

        if request.POST.get("cancel_reservations") == "on":
            # Cancel all reservations that haven't ended
            for reservation in dictionary["reservations"]:
                reservation.cancelled = True
                reservation.cancellation_time = timezone.now()
                reservation.cancelled_by = request.user
                reservation.save()
        if request.POST.get("disable_tools") == "on":
            # End all current tool usage
            for usage_event in dictionary["tool_usage"]:
                if usage_event.tool.interlock and not usage_event.tool.interlock.lock():
                    error_message = f"The interlock command for the {usage_event.tool} failed. The error message returned: {usage_event.tool.interlock.most_recent_reply}"
                    users_logger.error(error_message)
                usage_event.end = timezone.now()
                usage_event.save()
        if request.POST.get("force_area_logout") == "on":
            area_access = user_to_deactivate.area_access_record()
            if area_access:
                area_access.end = timezone.now()
                area_access.save()
        if request.POST.get("end_staff_charges") == "on":
            # End a staff charge that the user might be performing
            staff_charge = user_to_deactivate.get_staff_charge()
            if staff_charge:
                staff_charge.end = timezone.now()
                staff_charge.save()
                try:
                    area_access = AreaAccessRecord.objects.get(staff_charge=staff_charge, end=None)
                    area_access.end = timezone.now()
                    area_access.save()
                except AreaAccessRecord.DoesNotExist:
                    pass
            # End all staff charges that are being performed for the user
            for staff_charge in dictionary["staff_charges"]:
                staff_charge.end = timezone.now()
                staff_charge.save()
                try:
                    area_access = AreaAccessRecord.objects.get(staff_charge=staff_charge, end=None)
                    area_access.end = timezone.now()
                    area_access.save()
                except AreaAccessRecord.DoesNotExist:
                    pass
        user_to_deactivate.is_active = False
        user_to_deactivate.save()
        activity_entry = ActivityHistory()
        activity_entry.authorizer = request.user
        activity_entry.action = ActivityHistory.Action.DEACTIVATED
        activity_entry.content_object = user_to_deactivate
        activity_entry.save()

        message = f"{user_to_deactivate} has been successfully deactivated"
        messages.success(request, message)
        return redirect("users")


@user_office_or_manager_required
@require_POST
def reset_password(request, user_id):
    if identity_service.available:
        user = get_object_or_404(User, id=user_id)
        data, error = identity_service.reset_password(user.username, user.domain)
        if data:
            dictionary = {
                "title": "Password reset",
                "heading": "The account password was set to the default",
            }
        else:
            dictionary = {
                "title": "Oops",
                "heading": "There was a problem resetting the password",
                "content": error,
            }
    else:
        dictionary = {
            "title": "Identity service not available",
            "heading": "There was a problem resetting the password",
            "content": "The identity service is not set or not available",
        }
    return render(request, "acknowledgement.html", dictionary)


@user_office_or_manager_required
@require_POST
def unlock_account(request, user_id):
    if identity_service.available:
        user = get_object_or_404(User, id=user_id)
        data, error = identity_service.unlock_account(user.username, user.domain)
        if data:
            dictionary = {
                "title": "Account unlocked",
                "heading": "The account is now unlocked",
            }
        else:
            dictionary = {
                "title": "Oops",
                "heading": "There was a problem unlocking the account",
                "content": error,
            }
    else:
        dictionary = {
            "title": "Identity service not available",
            "heading": "There was a problem unlocking the account",
            "content": "The identity service is not set or not available",
        }
    return render(request, "acknowledgement.html", dictionary)


@login_required
@require_http_methods(["GET", "POST"])
def user_preferences(request):
    user: User = User.objects.get(pk=request.user.id)
    user_view_options = StatusDashboardCustomization.get("dashboard_staff_status_user_view")
    staff_view_options = StatusDashboardCustomization.get("dashboard_staff_status_staff_view")
    user_view = user_view_options if not user.is_staff else staff_view_options if not user.is_facility_manager else ""
    form = UserPreferencesForm(data=request.POST or None, instance=user.get_preferences())
    if not show_staff_status(request) or user_view == "day":
        form.fields["staff_status_view"].disabled = True
    if request.method == "POST":
        if form.is_valid():
            form.save()
            messages.success(request, "Your preferences have been saved")
        else:
            messages.error(request, "Please correct the errors below:")
    dictionary = {
        "form": form,
        "user_view": user_view,
        "tool_list": (
            user.qualifications.all()
            if not (user.is_staff or user.is_facility_manager or user.is_service_personnel)
            else Tool.objects.filter(visible=True)
        ),
    }
    return render(request, "users/preferences.html", dictionary)


@any_staff_required
@require_GET
def view_user(request, user_id):
    if UserCustomization.get_bool("user_allow_profile_view"):
        return render(request, "users/view_user.html", get_profile_dictionary(user_id))
    else:
        return HttpResponseBadRequest("You are not allowed to view this page")


@login_required
@require_GET
def user_profile(request):
    if UserCustomization.get_bool("user_allow_profile_view"):
        return render(request, "users/user_profile.html", get_profile_dictionary(request.user.id))
    else:
        return HttpResponseBadRequest("You are not allowed to view this page")


def get_profile_dictionary(user_id) -> dict:
    user = (
        User.objects.filter(pk=user_id)
        .prefetch_related(
            "qualifications",
            "groups",
            "physical_access_levels",
            "primary_tool_owner",
            "backup_for_tools",
            "staff_for_tools",
            "superuser_for_tools",
            "adjustment_request_reviewer_on_tools",
            "managed_projects",
            "managed_accounts",
        )
        .first()
    )
    if not user:
        raise Http404("No user matches the given query")

    return {
        "user_profile": user,
        "safety_trainings": SafetyTraining.objects.all(),
        "onboarding_phases": OnboardingPhase.objects.all(),
        "projects": Project.objects.filter(active=True, account__active=True),
    }


def readonly_users(request):
    # Only user office and facility managers can edit user information
    user: User = request.user
    return (
        user.is_any_part_of_staff and not user.is_facility_manager and not user.is_user_office and not user.is_superuser
    )
