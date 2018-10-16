from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from NEMO.models import Alert, LandingPageChoice, Reservation, Resource, UsageEvent
from NEMO.views.alerts import delete_expired_alerts
from NEMO.views.notifications import delete_expired_notifications, get_notificaiton_counts


@login_required
@require_GET
def landing(request):
	delete_expired_alerts()
	delete_expired_notifications()
	usage_events = UsageEvent.objects.filter(operator=request.user.id, end=None).prefetch_related('tool', 'project')
	tools_in_use = [u.tool_id for u in usage_events]
	fifteen_minutes_from_now = timezone.now() + timedelta(minutes=15)
	landing_page_choices = LandingPageChoice.objects.all()
	if request.device == 'desktop':
		landing_page_choices = landing_page_choices.exclude(hide_from_desktop_computers=True)
	if request.device == 'mobile':
		landing_page_choices = landing_page_choices.exclude(hide_from_mobile_devices=True)
	if not request.user.is_staff and not request.user.is_superuser and not request.user.is_technician:
		landing_page_choices = landing_page_choices.exclude(hide_from_users=True)
	dictionary = {
		'now': timezone.now(),
		'alerts': Alert.objects.filter(Q(user=None) | Q(user=request.user), debut_time__lte=timezone.now()),
		'usage_events': usage_events,
		'upcoming_reservations': Reservation.objects.filter(user=request.user.id, end__gt=timezone.now(), cancelled=False, missed=False, shortened=False).exclude(tool_id__in=tools_in_use, start__lte=fifteen_minutes_from_now).order_by('start')[:3],
		'disabled_resources': Resource.objects.filter(available=False),
		'landing_page_choices': landing_page_choices,
		'notification_counts': get_notificaiton_counts(request.user),
	}
	return render(request, 'landing.html', dictionary)
