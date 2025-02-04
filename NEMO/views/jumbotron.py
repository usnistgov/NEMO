from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from NEMO.models import Alert, Area, AreaAccessRecord, Resource, UsageEvent
from NEMO.views.alerts import mark_alerts_as_expired


@login_required
@require_GET
def jumbotron(request):
    return render(request, "jumbotron/jumbotron.html")


@login_required
@require_GET
def jumbotron_content(request):
    mark_alerts_as_expired()
    reservations_can_expire = Area.objects.filter(requires_reservation=True)
    dictionary = {
        "facility_occupants": AreaAccessRecord.objects.filter(end=None, staff_charge=None)
        .prefetch_related("customer", "project")
        .order_by("area__name", "start"),
        "usage_events": UsageEvent.objects.filter(end=None).prefetch_related("operator", "user", "tool"),
        "alerts": Alert.objects.filter(user=None, debut_time__lte=timezone.now(), expired=False, deleted=False),
        "disabled_resources": Resource.objects.filter(available=False),
        "reservations_can_expire": reservations_can_expire,
    }
    return render(request, "jumbotron/jumbotron_content.html", dictionary)
