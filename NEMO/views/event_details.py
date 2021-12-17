from django.contrib.auth.decorators import login_required
from django.http import HttpResponseNotFound
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET

from NEMO.models import Reservation
from NEMO.utilities import format_datetime


@login_required
@require_GET
def reservation_details(request, reservation_id):
	reservation = get_object_or_404(Reservation, id=reservation_id)
	popup_view = request.GET.get("popup_view")
	if reservation.cancelled:
		error_message = 'This reservation was cancelled by {0} at {1}.'.format(reservation.cancelled_by, format_datetime(reservation.cancellation_time))
		return HttpResponseNotFound(error_message)
	reservation_project_can_be_changed = (request.user.is_staff or request.user == reservation.user) and reservation.has_not_ended and reservation.has_not_started and reservation.user.active_project_count() > 1

	template_data = {
		'reservation': reservation,
		'reservation_project_can_be_changed': reservation_project_can_be_changed,
		'popup_view': popup_view
	}

	return render(request, 'event_details/reservation_details.html', template_data)
