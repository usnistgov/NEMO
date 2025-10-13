from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from NEMO.models import Alert, Area, AreaAccessRecord, Resource, UsageEvent
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
    display_alerts = request.GET.get("alerts", True) != "false"
    display_occupancy = request.GET.get("occupancy", True) != "false"
    display_usage = request.GET.get("usage", True) != "false"
    reservations_can_expire = Area.objects.filter(requires_reservation=True)
    dictionary = {
        "reservations_can_expire": reservations_can_expire,
        "display_alerts": display_alerts,
        "display_usage": display_usage,
        "display_occupancy": display_occupancy,
    }
    if display_alerts:
        dictionary["alerts"] = Alert.objects.filter(
            user=None, debut_time__lte=timezone.now(), expired=False, deleted=False
        )
        dictionary["disabled_resources"] = Resource.objects.filter(available=False)
    if display_occupancy:
        dictionary["facility_occupants"] = (
            AreaAccessRecord.objects.filter(end=None, staff_charge=None)
            .prefetch_related("customer", "project")
            .order_by("area__name", "start")
        )
    if display_usage:
        dictionary["usage_events"] = UsageEvent.objects.filter(end=None).prefetch_related("operator", "user", "tool")
    return render(request, "jumbotron/jumbotron_content.html", dictionary)
