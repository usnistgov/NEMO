from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import render
from django.utils import timezone
from datetime import timedelta
from django.views.decorators.http import require_GET

from NEMO.models import Alert, Area, AreaAccessRecord, Reservation, Resource, ScheduledOutage, UsageEvent
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
    display_alerts = request.GET.get("alerts", True) != "false"
    display_occupancy = request.GET.get("occupancy", True) != "false"
    reservations = request.GET.get("reservations", 0)
    display_reservations = str(reservations).isdigit() and int(reservations) > 0
    display_current_reservations = request.GET.get("current_reservations", False) == "true"
    display_scheduled_outages = request.GET.get("scheduled_outages", False) == "true"
    display_usage = request.GET.get("usage", True) != "false"
    reservations_can_expire = Area.objects.filter(requires_reservation=True)
    dictionary = {
        "reservations_can_expire": reservations_can_expire,
        "display_alerts": display_alerts,
        "display_usage": display_usage,
        "display_occupancy": display_occupancy,
        "display_reservations": display_reservations,
        "display_current_reservations": display_current_reservations,
        "display_scheduled_outages": display_scheduled_outages,
        "components": 0 # tracks the number of "tables/components" that will be displayed for easier layout calculation
    }
    if display_alerts:
        dictionary["alerts"] = Alert.objects.filter(
            user=None, debut_time__lte=timezone.now(), expired=False, deleted=False
        )
        dictionary["disabled_resources"] = Resource.objects.filter(available=False)
        if dictionary["alerts"] or dictionary["disabled_resources"]:
            dictionary["components"] = 1 # displayed with scheduled_outages, so set to 1 instead of +1
    if display_scheduled_outages:
        category_filter = Q()
        if tool_categories:
            for category in tool_categories:
                category_filter |= Q(tool___category__istartswith=category)
        dictionary["scheduled_outages"] = (
            ScheduledOutage.objects.filter(
                end__gt=timezone.now(),
                end__lte=timezone.now() + timedelta(days=1),
            ).filter(category_filter).order_by("start").prefetch_related("tool", "area", "resource")
        )
        if dictionary["scheduled_outages"]:
            dictionary["components"] = 1 # displayed with alerts & disabled_resources, so set to 1 instead of +1
    if display_occupancy:
        area_name_filter = Q()
        if area_names:
            for area_name in area_names:
                area_name_filter |= Q(area__name__iexact=area_name)
        dictionary["facility_occupants"] = (
            AreaAccessRecord.objects.filter(end=None, staff_charge=None)
            .filter(area_name_filter)
            .prefetch_related("customer", "project")
            .order_by("area__name", "start")
        )
        if dictionary["facility_occupants"]:
            dictionary["components"] = dictionary["components"] + 1
    if display_reservations:
        reservation_count = int(reservations)
        category_filter = Q()
        if tool_categories:
            for category in tool_categories:
                category_filter |= Q(tool___category__istartswith=category)
        # Set the filter criteria to end if in-progress reservations should also be displayed
        prefix = "end" if display_current_reservations else "start"
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
            ).filter(category_filter).order_by("start")[:reservation_count].prefetch_related("user", "tool", "area")
        )
        if dictionary["reservations"]:
            dictionary["components"] = dictionary["components"] + 1
    if display_usage:
        category_filter = Q()
        if tool_categories:
            for category in tool_categories:
                category_filter |= Q(tool___category__istartswith=category)
        dictionary["usage_events"] = (
            UsageEvent.objects.filter(end=None).filter(category_filter).prefetch_related("operator", "user", "tool")
        )
        if dictionary["usage_events"]:
            dictionary["components"] = dictionary["components"] + 1
    return render(request, "jumbotron/jumbotron_content.html", dictionary)
