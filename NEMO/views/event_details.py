from django.contrib.auth.decorators import login_required
from django.http import HttpResponseNotFound
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET
from django.db.models import Q
from django.utils import timezone

from NEMO.models import AreaAccessRecord, Reservation, ScheduledOutage, UsageEvent, User
from NEMO.utilities import format_datetime


@login_required
@require_GET
def reservation_details(request, reservation_id):
    reservation = get_object_or_404(Reservation, id=reservation_id)
    popup_view = request.GET.get("popup_view")
    if reservation.cancelled:
        error_message = "This reservation was cancelled by {0} at {1}.".format(
            reservation.cancelled_by, format_datetime(reservation.cancellation_time)
        )
        return HttpResponseNotFound(error_message)
    reservation_project_can_be_changed = (
        (request.user.is_staff or request.user == reservation.user)
        and reservation.has_not_ended
        and reservation.has_not_started
        and reservation.user.active_project_count() > 1
    )

    group_name = ""
    if request.user.groups is not None:
        r_user_groups = request.user.groups.all()
        for user_group in r_user_groups:
            if reservation.tool.name in user_group.name:
                group_name = user_group.name

    if reservation.tool is not None:
        if "24/7 User" in group_name:
            if reservation.daytimeusergroup_policy_check():
                # if reservation is in the daytime range, include daytime users in the list
                users = (
                    User.objects.filter(is_active=True)
                    .filter(
                        Q(groups__name__contains=group_name)
                        | (Q(groups__name__istartswith=reservation.tool.name) & Q(groups__name__iendswith="Daytime User"))
                    )
                    .exclude(username=request.user.username)
                )
            else:
                users = (
                    User.objects.filter(is_active=True)
                    .filter(Q(groups__name__contains=group_name))
                    .exclude(username=request.user.username)
                )
        else:
            users = (
                User.objects.filter(is_active=True)
                .filter(
                    Q(groups__name__contains=group_name)
                    | (Q(groups__name__istartswith=reservation.tool.name) & Q(groups__name__iendswith="24/7 User"))
                )
                .exclude(username=request.user.username)
            )
    else:
        users = User.objects.all()

    template_data = {
        "reservation": reservation,
        "reservation_project_can_be_changed": reservation_project_can_be_changed,
        "popup_view": popup_view,
        "users": users,
    }

    return render(request, "event_details/reservation_details.html", template_data)


@login_required
@require_GET
def outage_details(request, outage_id):
    outage = get_object_or_404(ScheduledOutage, id=outage_id)
    return render(
        request, "event_details/outage_details.html", {"outage": outage, "popup_view": request.GET.get("popup_view")}
    )


@login_required
@require_GET
def usage_details(request, event_id):
    event = get_object_or_404(UsageEvent, id=event_id)
    return render(
        request, "event_details/usage_details.html", {"event": event, "popup_view": request.GET.get("popup_view")}
    )


@login_required
@require_GET
def area_access_details(request, event_id):
    event = get_object_or_404(AreaAccessRecord, id=event_id)
    return render(
        request, "event_details/area_access_details.html", {"event": event, "popup_view": request.GET.get("popup_view")}
    )
