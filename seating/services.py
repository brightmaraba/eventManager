from django.db import IntegrityError, transaction
from django.utils import timezone

from audit.services import record
from core.errors import Conflict, DomainError, NotFound
from core.locking import lock_event
from events.services import bump
from guests.models import Ticket
from layouts.models import EventTable, Seat
from seating.models import Hold, SeatOccupancy


def _now():
    return timezone.now()


def hold_is_expired(hold, now=None):
    now = now or _now()
    return bool(hold and hold.released_at is None and hold.expires_at and hold.expires_at <= now)


def _same_event(event, seat=None, ticket=None, hold=None):
    if seat and seat.table.event_id != event.id:
        raise Conflict("cross_event", "That seat belongs to a different event.")
    if ticket and ticket.booking.event_id != event.id:
        raise Conflict("cross_event", "That ticket belongs to a different event.")
    if hold and hold.event_id != event.id:
        raise Conflict("cross_event", "That hold belongs to a different event.")


def _seat_usable(seat):
    return seat.availability == Seat.Availability.ACTIVE and seat.retired_at is None and seat.table.retired_at is None


def release_expired(event, actor, request_id):
    now = _now()
    holds = list(
        Hold.objects.select_for_update()
        .filter(event=event, released_at__isnull=True, expires_at__isnull=False, expires_at__lte=now)
        .order_by("id")
    )
    for hold in holds:
        for occupancy in list(hold.occupancies.select_for_update().order_by("id")):
            occupancy.delete()
        hold.released_at = now
        hold.save(update_fields=["released_at"])
        record(
            actor=actor,
            organization=event.organization,
            event=event,
            operation="hold_released",
            object_type="hold",
            object_id=hold.id,
            reason="expired",
            request_id=request_id,
            after={"purpose": hold.purpose},
        )
    return holds


def _lock_seat(seat_id):
    try:
        return Seat.objects.select_for_update().select_related("table").get(pk=seat_id)
    except Seat.DoesNotExist as exc:
        raise NotFound("That seat does not exist.") from exc


def _lock_ticket(ticket_id):
    try:
        return Ticket.objects.select_for_update().select_related("booking").get(pk=ticket_id)
    except Ticket.DoesNotExist as exc:
        raise NotFound("That ticket does not exist.") from exc


def impacts_for_seats(seats):
    occupancies = SeatOccupancy.objects.filter(seat__in=seats).select_related("ticket__booking", "hold", "seat__table")
    tickets = []
    holds = []
    for occupancy in occupancies:
        if occupancy.ticket_id:
            tickets.append({
                "ticket_id": str(occupancy.ticket_id),
                "label": occupancy.ticket.display_name,
                "seat_id": str(occupancy.seat_id),
                "seat_label": f"{occupancy.seat.table.label}-{occupancy.seat.label}",
            })
        elif occupancy.hold_id:
            holds.append({
                "hold_id": str(occupancy.hold_id),
                "purpose": occupancy.hold.purpose,
                "seat_id": str(occupancy.seat_id),
            })
    return {"tickets": tickets, "holds": holds}


def _require_resolution(seats):
    impacts = impacts_for_seats(seats)
    if impacts["tickets"] or impacts["holds"]:
        raise Conflict(
            "impact_unresolved",
            "Held or assigned seats have to be released or moved before this furniture change.",
            extra={"impacts": impacts},
        )


@transaction.atomic
def hold_seats(*, event, seat_ids, purpose, actor, request_id, reason="", expires_at=None, booking=None):
    event = lock_event(event.id)
    release_expired(event, actor, request_id)
    seats = list(Seat.objects.select_for_update().filter(pk__in=seat_ids).select_related("table").order_by("id"))
    if len(seats) != len(set(seat_ids)):
        raise NotFound("One or more seats do not exist.")
    for seat in seats:
        _same_event(event, seat=seat)
        if not _seat_usable(seat):
            raise Conflict("seat_unavailable", f"Seat {seat.label} cannot be held.")
    occupancies = list(SeatOccupancy.objects.select_for_update().filter(seat__in=seats).order_by("seat_id"))
    for occupancy in occupancies:
        if occupancy.hold_id and hold_is_expired(occupancy.hold):
            occupancy.delete()
            continue
        raise Conflict("seat_unavailable", "One of those seats is already held or assigned.")
    hold = Hold.objects.create(
        event=event, booking=booking, purpose=purpose, reason=reason, expires_at=expires_at, created_by=actor,
    )
    for seat in seats:
        SeatOccupancy.objects.create(seat=seat, hold=hold, assigned_by=actor)
    bump(event, layout=True)
    record(actor=actor, organization=event.organization, event=event, operation="seats_held", object_type="hold", object_id=hold.id, reason=reason, request_id=request_id, after={"seats": [str(seat.id) for seat in seats]})
    return {"hold_id": str(hold.id), "layout_revision": event.layout_revision}


@transaction.atomic
def hold_table(*, event, table_id, purpose, actor, request_id, reason="", expires_at=None, booking=None):
    event = lock_event(event.id)
    release_expired(event, actor, request_id)
    try:
        table = EventTable.objects.select_for_update().get(pk=table_id, event=event)
    except EventTable.DoesNotExist as exc:
        raise NotFound() from exc
    seats = list(table.seats.select_for_update().filter(availability=Seat.Availability.ACTIVE, retired_at__isnull=True).order_by("id"))
    if not seats:
        raise Conflict("no_seats", "This table has no active seats to hold.")
    occupancies = list(SeatOccupancy.objects.select_for_update().filter(seat__in=seats).order_by("seat_id"))
    for occupancy in occupancies:
        if occupancy.hold_id and hold_is_expired(occupancy.hold):
            occupancy.delete()
            continue
        raise Conflict("table_unavailable", "A seat on this table is already held or assigned.")
    hold = Hold.objects.create(
        event=event, table=table, whole_table=True, booking=booking, purpose=purpose, reason=reason,
        expires_at=expires_at, created_by=actor,
    )
    for seat in seats:
        SeatOccupancy.objects.create(seat=seat, hold=hold, assigned_by=actor)
    bump(event, layout=True)
    record(actor=actor, organization=event.organization, event=event, operation="table_held", object_type="hold", object_id=hold.id, reason=reason, request_id=request_id, after={"table_id": str(table.id)})
    return {"hold_id": str(hold.id), "layout_revision": event.layout_revision}


def cover_new_chair(seat, actor):
    hold = (
        Hold.objects.select_for_update()
        .filter(table=seat.table, whole_table=True, released_at__isnull=True)
        .order_by("id")
        .first()
    )
    if not hold or hold_is_expired(hold):
        return None
    return SeatOccupancy.objects.create(seat=seat, hold=hold, assigned_by=actor)


@transaction.atomic
def release_hold(*, event, hold_id, actor, request_id, reason=""):
    event = lock_event(event.id)
    try:
        hold = Hold.objects.select_for_update().get(pk=hold_id, event=event)
    except Hold.DoesNotExist as exc:
        raise NotFound() from exc
    if hold.released_at:
        return {"hold_id": str(hold.id), "released": True, "layout_revision": event.layout_revision}
    for occupancy in list(hold.occupancies.select_for_update().order_by("id")):
        occupancy.delete()
    hold.released_at = _now()
    hold.save(update_fields=["released_at"])
    bump(event, layout=True)
    record(actor=actor, organization=event.organization, event=event, operation="hold_released", object_type="hold", object_id=hold.id, reason=reason, request_id=request_id)
    return {"hold_id": str(hold.id), "released": True, "layout_revision": event.layout_revision}


def _take_occupancy(occupancy, ticket, actor, override_reason):
    if occupancy.ticket_id:
        if occupancy.ticket_id == ticket.id:
            return occupancy
        raise Conflict("seat_unavailable", "That seat is already assigned.")
    hold = occupancy.hold
    if hold_is_expired(hold):
        occupancy.delete()
        return None
    if hold.booking_id and hold.booking_id != ticket.booking_id:
        if not override_reason:
            raise Conflict("held_for_booking", "That seat is held for a different booking.")
        occupancy.delete()
        record_reason = override_reason
        hold_id = hold.id
        if not hold.occupancies.exists() or not hold.whole_table:
            remaining = hold.occupancies.exists()
            if not remaining:
                hold.released_at = _now()
                hold.save(update_fields=["released_at"])
        return "released"
    occupancy.ticket = ticket
    occupancy.hold = None
    occupancy.assigned_by = actor
    occupancy.save()
    if hold and not hold.occupancies.exists():
        hold.released_at = _now()
        hold.save(update_fields=["released_at"])
    return occupancy


@transaction.atomic
def assign(*, event, ticket_id, seat_id, actor, request_id, expected_version=None, override_reason=""):
    event = lock_event(event.id)
    if expected_version is not None and event.layout_revision != int(expected_version):
        raise Conflict("stale_version", "The layout changed. Refresh and try again.", revision=event.layout_revision)
    release_expired(event, actor, request_id)
    seat = _lock_seat(seat_id)
    ticket = _lock_ticket(ticket_id)
    _same_event(event, seat=seat, ticket=ticket)
    if ticket.status != Ticket.Status.ACTIVE:
        raise Conflict("ticket_inactive", "Cancelled tickets cannot be assigned.")
    if not _seat_usable(seat):
        raise Conflict("seat_unavailable", "Blocked or retired seats cannot be assigned.")
    existing = SeatOccupancy.objects.select_for_update().filter(ticket=ticket).first()
    if existing and existing.seat_id != seat.id:
        raise Conflict("ticket_seated", "That ticket already has a seat.")
    if existing and existing.seat_id == seat.id:
        return {"ticket_id": str(ticket.id), "seat_id": str(seat.id), "layout_revision": event.layout_revision, "unchanged": True}
    occupancy = SeatOccupancy.objects.select_for_update().filter(seat=seat).first()
    if occupancy:
        taken = _take_occupancy(occupancy, ticket, actor, override_reason)
        if taken is None or taken == "released":
            occupancy = None
        else:
            occupancy = taken
    if occupancy is None:
        try:
            with transaction.atomic():
                SeatOccupancy.objects.create(seat=seat, ticket=ticket, assigned_by=actor)
        except IntegrityError as exc:
            raise Conflict("seat_unavailable", "That seat is already taken.") from exc
    bump(event, layout=True)
    record(
        actor=actor, organization=event.organization, event=event, operation="seat_assigned", object_type="ticket",
        object_id=ticket.id, request_id=request_id, reason=override_reason, after={"seat_id": str(seat.id)},
    )
    return {"ticket_id": str(ticket.id), "seat_id": str(seat.id), "layout_revision": event.layout_revision}


@transaction.atomic
def unassign(*, event, ticket_id, actor, request_id, expected_version=None):
    event = lock_event(event.id)
    if expected_version is not None and event.layout_revision != int(expected_version):
        raise Conflict("stale_version", "The layout changed. Refresh and try again.", revision=event.layout_revision)
    ticket = _lock_ticket(ticket_id)
    _same_event(event, ticket=ticket)
    occupancy = SeatOccupancy.objects.select_for_update().filter(ticket=ticket).first()
    if not occupancy:
        return {"ticket_id": str(ticket.id), "layout_revision": event.layout_revision, "unchanged": True}
    seat_id = occupancy.seat_id
    occupancy.delete()
    bump(event, layout=True)
    record(actor=actor, organization=event.organization, event=event, operation="seat_unassigned", object_type="ticket", object_id=ticket.id, request_id=request_id, before={"seat_id": str(seat_id)})
    return {"ticket_id": str(ticket.id), "layout_revision": event.layout_revision}


def _available_seats(table):
    seats = []
    now = _now()
    for seat in table.seats.filter(availability=Seat.Availability.ACTIVE, retired_at__isnull=True).order_by("label"):
        occupancy = SeatOccupancy.objects.filter(seat=seat).select_related("hold").first()
        if occupancy and not (occupancy.hold_id and hold_is_expired(occupancy.hold, now)):
            continue
        seats.append(seat)
    return seats


@transaction.atomic
def group_assign(*, event, booking, table_id, actor, request_id, partial=False, preview=False, expected_version=None):
    event = lock_event(event.id)
    if expected_version is not None and event.layout_revision != int(expected_version):
        raise Conflict("stale_version", "The layout changed. Refresh and try again.", revision=event.layout_revision)
    release_expired(event, actor, request_id)
    try:
        table = EventTable.objects.select_for_update().get(pk=table_id, event=event)
    except EventTable.DoesNotExist as exc:
        raise NotFound() from exc
    tickets = [ticket for ticket in booking.tickets.select_for_update().filter(status=Ticket.Status.ACTIVE).order_by("sequence") if not SeatOccupancy.objects.filter(ticket=ticket).exists()]
    seats = _available_seats(table)
    if not tickets:
        return {"assignments": [], "layout_revision": event.layout_revision, "preview": preview}
    if len(seats) < len(tickets) and not partial:
        raise Conflict(
            "insufficient_capacity",
            f"This party needs {len(tickets)} seats and the table has {len(seats)} available.",
            extra={"needed": len(tickets), "available": len(seats)},
        )
    chosen_seats = seats[: len(tickets)]
    chosen_tickets = tickets[: len(chosen_seats)]
    plan = [{"ticket_id": str(ticket.id), "seat_id": str(seat.id), "seat_label": f"{table.label}-{seat.label}", "display_name": ticket.display_name} for ticket, seat in zip(chosen_tickets, chosen_seats)]
    if preview:
        return {"assignments": plan, "layout_revision": event.layout_revision, "preview": True}
    for ticket, seat in zip(chosen_tickets, chosen_seats):
        assign(event=event, ticket_id=ticket.id, seat_id=seat.id, actor=actor, request_id=request_id)
    event.refresh_from_db()
    return {"assignments": plan, "layout_revision": event.layout_revision, "preview": False}


@transaction.atomic
def swap(*, event, seat_a_id, seat_b_id, actor, request_id, expected_version=None):
    event = lock_event(event.id)
    if expected_version is not None and event.layout_revision != int(expected_version):
        raise Conflict("stale_version", "The layout changed. Refresh and try again.", revision=event.layout_revision)
    release_expired(event, actor, request_id)
    first_id, second_id = sorted([seat_a_id, seat_b_id], key=str)
    seats = list(Seat.objects.select_for_update().filter(pk__in=[first_id, second_id]).select_related("table").order_by("id"))
    if len(seats) != 2:
        raise NotFound("Both seats must exist.")
    for seat in seats:
        _same_event(event, seat=seat)
        if not _seat_usable(seat):
            raise Conflict("seat_unavailable", "Blocked or retired seats cannot be swapped.")
    occupancies = list(SeatOccupancy.objects.select_for_update().filter(seat__in=seats).order_by("seat_id"))
    by_seat = {occupancy.seat_id: occupancy for occupancy in occupancies}
    if any(occupancy.hold_id and not occupancy.ticket_id for occupancy in occupancies):
        raise Conflict("swap_needs_tickets", "Swap only assigned tickets.")
    if seats[0].id not in by_seat or seats[1].id not in by_seat:
        raise Conflict("swap_needs_tickets", "Both seats need an assigned ticket.")
    ticket_ids = sorted([by_seat[seats[0].id].ticket_id, by_seat[seats[1].id].ticket_id], key=str)
    list(Ticket.objects.select_for_update().filter(pk__in=ticket_ids).order_by("id"))
    left = by_seat[seats[0].id]
    right = by_seat[seats[1].id]
    left_ticket, right_ticket = left.ticket_id, right.ticket_id
    left_seat, right_seat = left.seat_id, right.seat_id
    left.delete()
    right.delete()
    try:
        with transaction.atomic():
            SeatOccupancy.objects.create(seat_id=left_seat, ticket_id=right_ticket, assigned_by=actor)
            SeatOccupancy.objects.create(seat_id=right_seat, ticket_id=left_ticket, assigned_by=actor)
    except IntegrityError as exc:
        raise Conflict("seat_unavailable", "The swap could not be completed.") from exc
    bump(event, layout=True)
    record(actor=actor, organization=event.organization, event=event, operation="seats_swapped", object_type="seat", object_id=left_seat, request_id=request_id, after={"seat_ids": [str(left_seat), str(right_seat)]})
    return {"layout_revision": event.layout_revision}


def apply_resolution(event, resolution, actor, request_id):
    resolution = resolution or {}
    for hold_id in resolution.get("release_hold_ids", []):
        release_hold(event=event, hold_id=hold_id, actor=actor, request_id=request_id, reason="furniture change")
    for item in resolution.get("reassign", []):
        assign(event=event, ticket_id=item["ticket_id"], seat_id=item["seat_id"], actor=actor, request_id=request_id)
    for ticket_id in resolution.get("unassign_ticket_ids", []):
        unassign(event=event, ticket_id=ticket_id, actor=actor, request_id=request_id)
