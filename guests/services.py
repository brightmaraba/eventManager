from django.db import transaction
from django.db.models import Max

from audit.services import record
from checkin.models import CheckIn
from core.errors import Conflict, DomainError
from core.locking import lock_event
from events.services import bump
from guests.models import Booking, Ticket
from seating.models import SeatOccupancy


def normalize_email(value):
    """Trim whitespace and lowercase the address. The original spelling is stored separately."""
    return (value or "").strip().lower()


def _protected(ticket):
    if SeatOccupancy.objects.filter(ticket=ticket).exists():
        return True
    return CheckIn.objects.filter(ticket=ticket, undone_at__isnull=True).exists()


def _refresh_labels(booking):
    active = list(booking.tickets.filter(status=Ticket.Status.ACTIVE).order_by("sequence"))
    total = len(active)
    party = booking.party_name or booking.original_email
    for ticket in active:
        if ticket.display_name_custom:
            continue
        ticket.display_name = f"{party} — guest {ticket.sequence}/{total}"
        ticket.save(update_fields=["display_name"])


def _impacts(tickets):
    return [
        {"ticket_id": str(ticket.id), "display_name": ticket.display_name, "sequence": ticket.sequence}
        for ticket in tickets
    ]


@transaction.atomic
def get_or_create_booking(*, event, email, party_name="", booking_reference="", notes="", actor=None, request_id=""):
    normalized = normalize_email(email)
    if not normalized or "@" not in normalized:
        raise DomainError("invalid_email", "Enter a valid email address.", field_errors={"email": "Enter a valid email address."})
    booking = Booking.objects.select_for_update().filter(event=event, normalized_email=normalized).first()
    created = False
    if booking is None:
        booking = Booking.objects.create(
            event=event,
            normalized_email=normalized,
            original_email=email.strip(),
            party_name=party_name or "",
            booking_reference=booking_reference or "",
            notes=notes or "",
        )
        created = True
    else:
        if party_name:
            booking.party_name = party_name
        if booking_reference:
            booking.booking_reference = booking_reference
        if notes:
            booking.notes = notes
        booking.save()
    return booking, created


@transaction.atomic
def set_quantity(*, event, booking, target, actor, request_id, bump_revision=True):
    from django.conf import settings

    event = lock_event(event.id)
    target = int(target)
    if target < 0:
        raise DomainError("invalid_quantity", "Ticket quantity cannot be negative.")
    if target > settings.IMPORT_MAX_TICKETS_PER_ROW:
        raise DomainError("invalid_quantity", f"A booking cannot exceed {settings.IMPORT_MAX_TICKETS_PER_ROW} tickets in one change.")
    booking = Booking.objects.select_for_update().get(pk=booking.id, event=event)
    active = list(booking.tickets.select_for_update().filter(status=Ticket.Status.ACTIVE).order_by("sequence"))
    if target == len(active):
        _refresh_labels(booking)
        return {"created": 0, "cancelled": []}
    if target > len(active):
        start = (booking.tickets.aggregate(highest=Max("sequence"))["highest"] or 0) + 1
        for sequence in range(start, start + target - len(active)):
            Ticket.objects.create(booking=booking, sequence=sequence, status=Ticket.Status.ACTIVE)
        _refresh_labels(booking)
        if bump_revision:
            bump(event, roster=True, layout=bool(event.active_publication_id))
        record(actor=actor, organization=event.organization, event=event, operation="tickets_added", object_type="booking", object_id=booking.id, request_id=request_id, after={"quantity": target})
        return {"created": target - len(active), "cancelled": []}
    need = len(active) - target
    removable = [ticket for ticket in reversed(active) if not _protected(ticket)]
    protected = [ticket for ticket in active if _protected(ticket)]
    if len(removable) < need:
        raise Conflict(
            "protected_tickets",
            "Assigned or checked-in tickets cannot be removed until they are unassigned or reversed.",
            extra={"impacts": _impacts(protected)},
        )
    cancelled = []
    for ticket in removable[:need]:
        ticket.status = Ticket.Status.CANCELLED
        ticket.save(update_fields=["status"])
        cancelled.append(str(ticket.id))
    _refresh_labels(booking)
    if bump_revision:
        bump(event, roster=True, layout=bool(event.active_publication_id))
    record(actor=actor, organization=event.organization, event=event, operation="tickets_reduced", object_type="booking", object_id=booking.id, request_id=request_id, after={"quantity": target, "cancelled": cancelled})
    return {"created": 0, "cancelled": cancelled}


@transaction.atomic
def update_attendee(*, event, ticket, display_name, actor, request_id):
    event = lock_event(event.id)
    ticket.display_name = display_name.strip()
    ticket.display_name_custom = True
    ticket.save(update_fields=["display_name", "display_name_custom"])
    record(actor=actor, organization=event.organization, event=event, operation="attendee_renamed", object_type="ticket", object_id=ticket.id, request_id=request_id)
    return ticket


@transaction.atomic
def cancel_ticket(*, event, ticket, actor, request_id, reason):
    event = lock_event(event.id)
    if SeatOccupancy.objects.filter(ticket=ticket).exists() or CheckIn.objects.filter(ticket=ticket, undone_at__isnull=True).exists():
        raise Conflict("protected_tickets", "Unassign this ticket and undo check-in before cancelling it.", extra={"impacts": _impacts([ticket])})
    ticket.status = Ticket.Status.CANCELLED
    ticket.save(update_fields=["status"])
    from guests.tokens import revoke_ticket_tokens

    revoke_ticket_tokens(ticket)
    if event.active_publication_id:
        event.republish_required = True
        event.save(update_fields=["republish_required", "updated_at"])
    bump(event, roster=True, layout=bool(event.active_publication_id))
    record(actor=actor, organization=event.organization, event=event, operation="ticket_cancelled", object_type="ticket", object_id=ticket.id, reason=reason, request_id=request_id)
    return ticket
