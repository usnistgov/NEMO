from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import render, get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST, require_http_methods

from NEMO.forms import AlertForm
from NEMO.models import Alert


@staff_member_required(login_url=None)
@require_http_methods(['GET', 'POST'])
def alerts(request):
	alert_id = request.GET.get('alert_id') or request.POST.get('alert_id')
	try:
		alert = Alert.objects.get(id=alert_id)
	except:
		alert = None
	if request.method == 'GET':
		form = AlertForm(instance=alert)
	elif request.method == 'POST':
		form = AlertForm(data=request.POST, instance=alert)
		if form.is_valid():
			alert = form.save()
			if not alert.creator:
				alert.creator = request.user
			alert.save()
			form = AlertForm()
	else:
		form = AlertForm()
	dictionary = {
		'form': form,
		'editing': True if form.instance.id else False,
		'alerts': Alert.objects.filter(user=None)
	}
	delete_expired_alerts()
	return render(request, 'alerts.html', dictionary)


@login_required
@require_POST
def delete_alert(request, alert_id):
	try:
		alert = get_object_or_404(Alert, id=alert_id)
		if alert.user == request.user:  # Users can delete their own alerts
			alert.delete()
		elif alert.user is None and request.user.is_staff:  # Staff can delete global alerts
			alert.delete()
	except Http404:
		pass
	return redirect(request.META.get('HTTP_REFERER', 'landing'))


def delete_expired_alerts():
	Alert.objects.filter(expiration_time__lt=timezone.now()).delete()
