from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from audit.services import record
from checkin.models import CheckIn
from core.errors import Conflict, DomainError, NotFound
from core.locking import lock_event
from guests.models import Ticket
from guests.tokens import resolve_token


@transaction.atomic
def check_in(*, event, ticket_id, actor, request_id, device_ref="", idempotency_note=""):
    event = lock_event(event.id)
    try:
        ticket = Ticket.objects.select_for_update().select_related("booking").get(pk=ticket_id, booking__event=event)
    except Ticket.DoesNotExist as exc:
        raise NotFound() from exc
    if ticket.status != Ticket.Status.ACTIVE:
        raise Conflict("ticket_inactive", "Cancelled tickets cannot be checked in.")
    existing = CheckIn.objects.select_for_update().filter(ticket=ticket).first()
    if existing and existing.is_current:
        return {"ticket_id": str(ticket.id), "checked_in_at": existing.checked_in_at.isoformat(), "already_checked_in": True}
    now = timezone.now()
    if existing:
        existing.checked_in_at = now
        existing.checked_in_by = actor
        existing.device_ref = device_ref
        existing.undone_at = None
        existing.undone_by = None
        existing.undo_reason = ""
        existing.save()
        row = existing
    else:
        row = CheckIn.objects.create(ticket=ticket, checked_in_at=now, checked_in_by=actor, device_ref=device_ref)
    record(actor=actor, organization=event.organization, event=event, operation="checked_in", object_type="ticket", object_id=ticket.id, request_id=request_id, after={"at": row.checked_in_at.isoformat()})
    return {"ticket_id": str(ticket.id), "checked_in_at": row.checked_in_at.isoformat(), "already_checked_in": False}


@transaction.atomic
def undo_check_in(*, event, ticket_id, actor, request_id, reason):
    if not reason:
        raise DomainError("reason_required", "Undoing a check-in requires a reason.")
    event = lock_event(event.id)
    try:
        ticket = Ticket.objects.select_for_update().get(pk=ticket_id, booking__event=event)
    except Ticket.DoesNotExist as exc:
        raise NotFound() from exc
    existing = CheckIn.objects.select_for_update().filter(ticket=ticket).first()
    if not existing or not existing.is_current:
        raise Conflict("not_checked_in", "That ticket is not checked in.")
    existing.undone_at = timezone.now()
    existing.undone_by = actor
    existing.undo_reason = reason
    existing.save(update_fields=["undone_at", "undone_by", "undo_reason"])
    record(actor=actor, organization=event.organization, event=event, operation="check_in_undone", object_type="ticket", object_id=ticket.id, reason=reason, request_id=request_id)
    return {"ticket_id": str(ticket.id), "undone": True}


def check_in_token(*, raw_token, actor, request_id, device_ref=""):
    token = resolve_token(raw_token, "checkin")
    if token is None or token.ticket_id is None:
        raise NotFound("That check-in code is not valid.")
    return check_in(event=token.ticket.booking.event, ticket_id=token.ticket_id, actor=actor, request_id=request_id, device_ref=device_ref)


def party_progress(booking):
    active = list(booking.tickets.filter(status=Ticket.Status.ACTIVE).order_by("sequence"))
    arrived = CheckIn.objects.filter(ticket__in=active, undone_at__isnull=True).count()
    return {"arrived": arrived, "total": len(active)}
