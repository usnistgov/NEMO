from logging import getLogger

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseNotFound, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET

from NEMO.models import Reservation
from NEMO.utilities import format_datetime
detail_logger = getLogger(__name__)


@login_required
@require_GET
def reservation(request, reservation_id) -> HttpResponse:
    """ Present a reservation detail view to the user. """
    reservation = get_object_or_404(Reservation, id=reservation_id)

    if reservation.cancelled:
        error_message = 'This reservation was cancelled by {0} at {1}.'.format(
            reservation.cancelled_by,
            format_datetime(reservation.cancellation_time))
        return HttpResponseNotFound(error_message)

    reservation_project_can_be_changed = (
        request.user.is_staff or
        request.user ==
        reservation.user) and \
        reservation.has_not_ended and \
        reservation.has_not_started and \
        reservation.user.active_project_count() > 1

    dictionary = {
        'reservation': reservation,
        'reservation_project_can_be_changed': reservation_project_can_be_changed
    }
    return render(request, 'reservation_detail.html', dictionary)
