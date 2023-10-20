from logging import getLogger

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods

from NEMO.decorators import user_office_or_manager_required
from NEMO.forms import TemporaryPhysicalAccessRequestForm
from NEMO.models import (
    Area,
    Notification,
    PhysicalAccessLevel,
    RequestStatus,
    TemporaryPhysicalAccess,
    TemporaryPhysicalAccessRequest,
    User,
)
from NEMO.typing import QuerySetType
from NEMO.utilities import (
    BasicDisplayTable,
    EmailCategory,
    bootstrap_primary_color,
    export_format_datetime,
    get_full_url,
    quiet_int,
    render_email_template,
    send_mail,
    slugify_underscore,
)
from NEMO.views.customization import (
    UserRequestsCustomization,
    get_media_file_contents,
)
from NEMO.views.notifications import create_access_request_notification, delete_notification, get_notifications

access_request_logger = getLogger(__name__)


@login_required
@require_GET
def access_requests(request):
    mark_requests_expired()
    user: User = request.user
    max_requests = quiet_int(UserRequestsCustomization.get("access_requests_display_max"), None)
    physical_access_requests = TemporaryPhysicalAccessRequest.objects.filter(deleted=False)
    physical_access_requests = physical_access_requests.order_by("-end_time")

    # For some reason doing an "or" filtering with manytomany field returns duplicates, and using distinct() returns nothing...
    other_user_physical_access_requests = physical_access_requests.filter(other_users__in=[user]).distinct()
    my_requests = physical_access_requests.filter(Q(creator=user) | Q(id__in=other_user_physical_access_requests))

    user_is_reviewer = is_user_a_reviewer(user)
    user_is_staff = user.is_facility_manager or user.is_user_office or user.is_staff
    if not user_is_reviewer and not user_is_staff:
        physical_access_requests = my_requests
    elif user_is_reviewer:
        # show all requests the user can review (+ his requests), exclude the rest
        exclude = []
        for access_request in physical_access_requests:
            if user not in access_request.creator_and_other_users() and user not in access_request.reviewers():
                exclude.append(access_request.pk)
        physical_access_requests = physical_access_requests.exclude(pk__in=exclude)
    dictionary = {
        "pending_access_requests": physical_access_requests.filter(status=RequestStatus.PENDING).order_by("start_time"),
        "approved_access_requests": physical_access_requests.filter(status=RequestStatus.APPROVED)[:max_requests],
        "denied_access_requests": physical_access_requests.filter(status=RequestStatus.DENIED)[:max_requests],
        "expired_access_requests": physical_access_requests.filter(status=RequestStatus.EXPIRED)[:max_requests],
        "access_requests_description": UserRequestsCustomization.get("access_requests_description"),
        "access_request_notifications": get_notifications(
            request.user, Notification.Types.TEMPORARY_ACCESS_REQUEST, delete=False
        ),
        "user_is_reviewer": user_is_reviewer,
    }

    # Delete notifications for seen requests
    Notification.objects.filter(
        user=request.user, notification_type=Notification.Types.TEMPORARY_ACCESS_REQUEST, object_id__in=my_requests
    ).delete()
    return render(request, "requests/access_requests/access_requests.html", dictionary)


@login_required
@require_http_methods(["GET", "POST"])
def create_access_request(request, request_id=None):
    user: User = request.user
    try:
        access_request = TemporaryPhysicalAccessRequest.objects.get(id=request_id)
    except TemporaryPhysicalAccessRequest.DoesNotExist:
        access_request = None

    dictionary = {
        "physical_access_levels": PhysicalAccessLevel.objects.filter(allow_user_request=True),
        "other_users": User.objects.filter(is_active=True).exclude(id=user.id),
    }

    if request.method == "POST":
        # some extra validation needs to be done here because it depends on the user
        edit = bool(access_request)
        errors = []
        if edit:
            if access_request.deleted:
                errors.append("You are not allowed to edit expired or deleted requests.")
            if access_request.status != RequestStatus.PENDING:
                errors.append("Only pending requests can be modified.")
            if access_request.creator != user and not user in access_request.reviewers():
                errors.append("You are not allowed to edit this request.")

        form = TemporaryPhysicalAccessRequestForm(
            request.POST, instance=access_request, initial={"creator": access_request.creator if edit else user}
        )

        # add errors to the form for better display
        for error in errors:
            form.add_error(None, error)

        cleaned_data = form.clean()
        if (
            cleaned_data
            and (not edit or user not in access_request.reviewers())
            and cleaned_data.get("start_time") < timezone.now()
        ):
            form.add_error("start_time", "The start time must be later than the current time")

        if form.is_valid():
            if not edit:
                form.instance.creator = user
            if edit and user in access_request.reviewers():
                decision = [state for state in ["approve_request", "deny_request"] if state in request.POST]
                if decision:
                    if next(iter(decision)) == "approve_request":
                        access_request.status = RequestStatus.APPROVED
                        create_temporary_access(access_request)
                    else:
                        access_request.status = RequestStatus.DENIED
                    access_request.reviewer = user

            form.instance.last_updated_by = user
            new_access_request = form.save()
            create_access_request_notification(new_access_request)
            if edit:
                # remove notification for current user and other reviewers
                delete_notification(Notification.Types.TEMPORARY_ACCESS_REQUEST, new_access_request.id, [user])
                if user in access_request.reviewers():
                    delete_notification(
                        Notification.Types.TEMPORARY_ACCESS_REQUEST, new_access_request.id, access_request.reviewers()
                    )
            send_request_received_email(request, new_access_request, edit)
            return redirect("user_requests", "access")
        else:
            dictionary["form"] = form
            return render(request, "requests/access_requests/access_request.html", dictionary)
    else:
        form = TemporaryPhysicalAccessRequestForm(instance=access_request)
        dictionary["form"] = form
        return render(request, "requests/access_requests/access_request.html", dictionary)


@login_required
@require_GET
def delete_access_request(request, request_id):
    access_request = get_object_or_404(TemporaryPhysicalAccessRequest, id=request_id)

    if access_request.creator != request.user:
        return HttpResponseBadRequest("You are not allowed to delete a request you didn't create.")
    if access_request and access_request.status != RequestStatus.PENDING:
        return HttpResponseBadRequest("You are not allowed to delete a request that is not pending.")

    access_request.deleted = True
    access_request.save(update_fields=["deleted"])
    delete_notification(Notification.Types.TEMPORARY_ACCESS_REQUEST, access_request.id)
    return redirect("user_requests", "access")


def create_temporary_access(access_request: TemporaryPhysicalAccessRequest):
    for user in access_request.creator_and_other_users():
        TemporaryPhysicalAccess.objects.create(
            user=user,
            physical_access_level=access_request.physical_access_level,
            start_time=access_request.start_time,
            end_time=access_request.end_time,
        )


def mark_requests_expired():
    for expired_request in TemporaryPhysicalAccessRequest.objects.filter(
        status=RequestStatus.PENDING, deleted=False, end_time__lt=timezone.now()
    ):
        delete_notification(Notification.Types.TEMPORARY_ACCESS_REQUEST, expired_request.id)
        expired_request.status = RequestStatus.EXPIRED
        expired_request.save(update_fields=["status"])


def send_request_received_email(request, access_request: TemporaryPhysicalAccessRequest, edit):
    access_request_notification_email = get_media_file_contents("access_request_notification_email.html")
    if access_request_notification_email:
        # reviewers
        reviewer_emails = [
            email
            for user in access_request.reviewers()
            for email in user.get_emails(user.get_preferences().email_send_adjustment_request_updates)
        ]
        # cc creator + other users
        cc_users = access_request.creator_and_other_users()
        ccs = [
            email
            for user in cc_users
            for email in user.get_emails(user.get_preferences().email_send_access_request_updates)
        ]
        status = (
            "approved"
            if access_request.status == RequestStatus.APPROVED
            else "denied"
            if access_request.status == RequestStatus.DENIED
            else "updated"
            if edit
            else "received"
        )
        absolute_url = get_full_url(reverse("user_requests", kwargs={"tab": "access"}), request)
        color_type = "success" if status == "approved" else "danger" if status == "denied" else "info"
        message = render_email_template(
            access_request_notification_email,
            {
                "template_color": bootstrap_primary_color(color_type),
                "access_request": access_request,
                "status": status,
                "access_requests_url": absolute_url,
            },
        )
        if status in ["received", "updated"]:
            send_mail(
                subject=f"Access request for the {access_request.physical_access_level.area} {status}",
                content=message,
                from_email=access_request.creator.email,
                to=reviewer_emails,
                cc=ccs,
                email_category=EmailCategory.ACCESS_REQUESTS,
            )
        else:
            send_mail(
                subject=f"Your access request for the {access_request.physical_access_level.area} has been {status}",
                content=message,
                from_email=access_request.reviewer.email,
                to=ccs,
                cc=reviewer_emails,
                email_category=EmailCategory.ACCESS_REQUESTS,
            )


@user_office_or_manager_required
@require_GET
def csv_export(request):
    return access_csv_export(TemporaryPhysicalAccessRequest.objects.filter(deleted=False))


def access_csv_export(request_qs: QuerySetType[TemporaryPhysicalAccessRequest]) -> HttpResponse:
    table_result = BasicDisplayTable()
    table_result.add_header(("status", "Status"))
    table_result.add_header(("created_date", "Created date"))
    table_result.add_header(("last_updated", "Last updated"))
    table_result.add_header(("creator", "Creator"))
    table_result.add_header(("other_users", "Buddies"))
    table_result.add_header(("area", "Area"))
    table_result.add_header(("access_level", "Access level"))
    table_result.add_header(("start", "Start"))
    table_result.add_header(("end", "End"))
    table_result.add_header(("reviewer", "Reviewer"))
    for req in request_qs:
        table_result.add_row(
            {
                "status": req.get_status_display(),
                "created_date": req.creation_time,
                "last_updated": req.last_updated,
                "creator": req.creator,
                "other_users": ", ".join([str(user) for user in req.other_users.all()]),
                "area": req.physical_access_level.area,
                "access_level": req.physical_access_level,
                "start": req.start_time,
                "end": req.end_time,
                "reviewer": req.reviewer,
            }
        )

    name = slugify_underscore(UserRequestsCustomization.get("access_requests_title"))
    filename = f"{name}_{export_format_datetime()}.csv"
    response = table_result.to_csv()
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def is_user_a_reviewer(user: User) -> bool:
    is_reviewer_on_any_area = Area.objects.filter(access_request_reviewers__in=[user]).exists()
    return user.is_facility_manager or is_reviewer_on_any_area
