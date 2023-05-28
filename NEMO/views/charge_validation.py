from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from NEMO.decorators import staff_member_required
from NEMO.models import AreaAccessRecord, ConsumableWithdraw, Reservation, StaffCharge, TrainingSession, UsageEvent


@staff_member_required
@require_POST
def validate_staff_charge(request, staff_charge_id):
    staff_charge = get_object_or_404(StaffCharge, id=staff_charge_id)
    staff_charge.validated = True
    staff_charge.validated_by = request.user
    staff_charge.save()
    # Validate associated area access records
    for area_access_record in staff_charge.areaaccessrecord_set.all():
        validate_area_access_record(request, area_access_record.id)
    return HttpResponse()


@staff_member_required
@require_POST
def validate_usage_event(request, usage_event_id):
    usage_event = get_object_or_404(UsageEvent, id=usage_event_id)
    usage_event.validated = True
    usage_event.validated_by = request.user
    usage_event.save()
    return HttpResponse()


@staff_member_required
@require_POST
def validate_area_access_record(request, area_access_record_id):
    area_access = get_object_or_404(AreaAccessRecord, id=area_access_record_id)
    area_access.validated = True
    area_access.validated_by = request.user
    area_access.save()
    return HttpResponse()


@staff_member_required
@require_POST
def validate_missed_reservation(request, reservation_id):
    missed_reservation = get_object_or_404(Reservation, id=reservation_id, missed=True)
    missed_reservation.validated = True
    missed_reservation.validated_by = request.user
    missed_reservation.save()
    return HttpResponse()


@staff_member_required
@require_POST
def validate_training_session(request, training_session_id):
    training_session = get_object_or_404(TrainingSession, id=training_session_id)
    training_session.validated = True
    training_session.validated_by = request.user
    training_session.save()
    return HttpResponse()


@staff_member_required
@require_POST
def validate_consumable_withdrawal(request, consumable_withdraw_id):
    withdraw = get_object_or_404(ConsumableWithdraw, id=consumable_withdraw_id)
    withdraw.validated = True
    withdraw.validated_by = request.user
    withdraw.save()
    return HttpResponse()
