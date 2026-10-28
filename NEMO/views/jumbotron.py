from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import render
from django.utils import timezone
from datetime import timedelta
from django.views.decorators.http import require_GET

from NEMO.models import Alert, Area, AreaAccessRecord, Reservation, Resource, ScheduledOutage, UsageEvent
from NEMO.utilities import quiet_int
from NEMO.views.alerts import mark_alerts_as_expired
from NEMO.views.customization import get_media_file_contents


@login_required
@require_GET
def jumbotron(request):
    return render(
        request, "jumbotron/jumbotron.html", {"watermark": bool(get_media_file_contents("jumbotron_watermark.png"))}
    )


@login_required
@require_GET
def jumbotron_content(request):
    mark_alerts_as_expired()
    area_names = request.GET.getlist("area", [])
    tool_categories = request.GET.getlist("category", [])
    reservations = quiet_int(request.GET.get("reservations"), 0)

    tool_category_filter = Q()
    if tool_categories:
        for category in tool_categories:
            tool_category_filter |= Q(tool___category__istartswith=category)
    area_name_filter = Q()
    if area_names:
        for area_name in area_names:
            area_name_filter |= Q(area__name__iexact=area_name)

    dictionary = {
        "reservations_can_expire": Area.objects.filter(requires_reservation=True),
        "display_usage": request.GET.get("usage", True) != "false",
        "display_occupancy": request.GET.get("occupancy", True) != "false",
        "display_reservations": reservations > 0,
        "display_current_reservations": request.GET.get("current_reservations", False) == "true",
    }

    if request.GET.get("alerts", True) != "false":
        dictionary["alerts"] = Alert.objects.filter(
            user=None, debut_time__lte=timezone.now(), expired=False, deleted=False
        )
        dictionary["disabled_resources"] = Resource.objects.filter(available=False)
    if request.GET.get("scheduled_outages", False) == "true":
        dictionary["scheduled_outages"] = (
            ScheduledOutage.objects.filter(
                end__gt=timezone.now(),
                end__lte=timezone.now() + timedelta(days=1),
            )
            .filter(tool_category_filter)
            .order_by("start")
            .prefetch_related("tool", "area", "resource")
        )
    if dictionary["display_occupancy"]:
        dictionary["facility_occupants"] = (
            AreaAccessRecord.objects.filter(end=None, staff_charge=None)
            .filter(area_name_filter)
            .prefetch_related("customer", "project")
            .order_by("area__name", "start")
        )
    if dictionary["display_reservations"]:
        # Set the filter criteria to end if in-progress reservations should also be displayed
        prefix = "end" if dictionary["display_current_reservations"] else "start"
        time_filters = {
            f"{prefix}__gt": timezone.now(),
            f"{prefix}__lte": timezone.now() + timedelta(weeks=1),
        }
        dictionary["reservations"] = (
            Reservation.objects.filter(
                cancelled=False,
                missed=False,
                shortened=False,
                **time_filters,
            )
            .filter(tool_category_filter)
            .order_by("start")[:reservations]
            .prefetch_related("user", "tool", "area")
        )
    if dictionary["display_usage"]:
        dictionary["usage_events"] = (
            UsageEvent.objects.filter(end=None)
            .filter(tool_category_filter)
            .prefetch_related("operator", "user", "tool")
        )

    # Calculate components
    # Alerts and scheduled outages share a single component block.
    # Occupants, reservations, and usage each get their own.
    # bool(QuerySet) efficiently checks if results exist.
    dictionary["components"] = sum(
        [
            bool(
                dictionary.get("alerts") or dictionary.get("disabled_resources") or dictionary.get("scheduled_outages")
            ),
            bool(dictionary.get("facility_occupants")),
            bool(dictionary.get("reservations")),
            bool(dictionary.get("usage_events")),
        ]
    )
    return render(request, "jumbotron/jumbotron_content.html", dictionary)
