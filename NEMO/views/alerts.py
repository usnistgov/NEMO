import datetime

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST, require_http_methods

from NEMO.decorators import staff_member_or_user_office_required
from NEMO.forms import AlertForm
from NEMO.models import Alert, AlertCategory


@staff_member_or_user_office_required
@require_http_methods(["GET", "POST"])
def alerts(request):
    alert_id = request.GET.get("alert_id") or request.POST.get("alert_id")
    try:
        alert = Alert.objects.get(id=alert_id)
    except Alert.DoesNotExist:
        alert = None
    if request.method == "POST":
        form = AlertForm(data=request.POST, instance=alert)
        if form.is_valid():
            alert = form.save()
            if not alert.creator:
                alert.creator = request.user
            alert.save()
            form = AlertForm()
    else:
        form = AlertForm(instance=alert)
    dictionary = {
        "form": form,
        "editing": True if form.instance.id else False,
        "alerts": Alert.objects.filter(user=None, expired=False, deleted=False),
        "now": datetime.datetime.now(),
        "alert_categories": AlertCategory.objects.all(),
    }
    mark_alerts_as_expired()
    return render(request, "alerts.html", dictionary)


@login_required
@require_POST
def delete_alert(request, alert_id):
    alert = get_object_or_404(Alert, id=alert_id)
    if alert.user == request.user:  # Users can delete their own alerts
        alert.deleted = True
        alert.save(update_fields=["deleted"])
    elif alert.user is None and request.user.is_staff:  # Staff can delete global alerts
        alert.deleted = True
        alert.save(update_fields=["deleted"])
    return redirect(request.META.get("HTTP_REFERER", "landing"))


def mark_alerts_as_expired():
    Alert.objects.filter(expired=False, expiration_time__lt=timezone.now()).update(expired=True)
