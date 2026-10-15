from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from audit.services import record
from core.errors import Conflict, DomainError, NotFound
from core.locking import lock_event
from events.services import bump
from layouts.geometry import chair_offsets, quantize, validate_layout
from layouts.models import EventTable, Room, Seat


def ensure_room(event, width=Decimal("30"), height=Decimal("20")):
    room = event.rooms.first()
    if room:
        return room
    return Room.objects.create(event=event, width_m=width, height_m=height, name="Main room")


def _open_center(room, width, height):
    spacing = Decimal("4")
    columns = max(1, int((room.width_m - spacing) / spacing))
    existing = list(room.tables.filter(retired_at__isnull=True))
    for index in range(columns * 8):
        row, column = divmod(index, columns)
        x = Decimal("2.5") + Decimal(column) * spacing
        y = Decimal("2.5") + Decimal(row) * spacing
        if x + Decimal(str(width)) / 2 > room.width_m or y + Decimal(str(height)) / 2 > room.height_m:
            continue
        if any(
            abs(table.center_x - x) < Decimal("3.5") and abs(table.center_y - y) < Decimal("3.5")
            for table in existing
        ):
            continue
        return x, y
    raise DomainError("room_full", "There is no open space for another table.")


def _next_label(event):
    labels = set(event.tables.filter(retired_at__isnull=True).values_list("label", flat=True))
    number = 1
    while f"T{number}" in labels:
        number += 1
    return f"T{number}"


def _create_seats(table, count):
    created = []
    existing = table.seats.count()
    for index, (rel_x, rel_y, orientation) in enumerate(chair_offsets(count, table.width_m), start=existing + 1):
        seat = Seat.objects.create(table=table, label=str(index), rel_x=rel_x, rel_y=rel_y, orientation=orientation)
        created.append(seat)
    return created


def _create_table(event, room, *, label, shape, width, height, x, y, rotation, seats, actor, polygon=None):
    table = EventTable.objects.create(
        event=event,
        room=room,
        label=label or _next_label(event),
        shape=shape,
        width_m=quantize(width),
        height_m=quantize(height if shape != "round" else width),
        center_x=quantize(x),
        center_y=quantize(y),
        rotation=quantize(rotation or 0),
        polygon=polygon or [],
    )
    _create_seats(table, seats)
    return table


@transaction.atomic
def create_table(*, event, actor, request_id, shape="round", width="1.6", height="1.6", x=None, y=None, rotation=0, seats=8, label="", override_reason=""):
    event = lock_event(event.id)
    room = ensure_room(event)
    if x in (None, "") or y in (None, ""):
        x, y = _open_center(room, width, height)
    table = _create_table(event, room, label=label, shape=shape, width=width, height=height, x=x, y=y, rotation=rotation, seats=int(seats), actor=actor)
    warnings = validate_layout(room, list(event.tables.filter(retired_at__isnull=True)), override_reason)
    from seating.services import cover_new_chair

    for seat in table.seats.all():
        cover_new_chair(seat, actor)
    bump(event, layout=True)
    if warnings:
        record(actor=actor, organization=event.organization, event=event, operation="clearance_override", object_type="table", object_id=table.id, reason=override_reason, request_id=request_id, after={"warnings": warnings})
    record(actor=actor, organization=event.organization, event=event, operation="table_created", object_type="table", object_id=table.id, request_id=request_id, after={"label": table.label, "seats": table.seats.count()})
    return table


@transaction.atomic
def generate_tables(event, room, count, seats_per_table, actor, request_id):
    event = lock_event(event.id)
    spacing = Decimal("4")
    columns = max(1, int((room.width_m - Decimal("5")) / spacing))
    created = []
    for index in range(int(count)):
        row, column = divmod(index, columns)
        created.append(
            _create_table(
                event, room, label="", shape="round", width="1.6", height="1.6",
                x=Decimal("2.5") + Decimal(column) * spacing,
                y=Decimal("2.5") + Decimal(row) * spacing,
                rotation=0, seats=int(seats_per_table), actor=actor,
            )
        )
    validate_layout(room, list(event.tables.filter(retired_at__isnull=True)))
    bump(event, layout=True)
    record(actor=actor, organization=event.organization, event=event, operation="tables_generated", object_type="event", object_id=event.id, request_id=request_id, after={"count": len(created)})
    return created


@transaction.atomic
def duplicate_table(*, event, table_id, actor, request_id):
    event = lock_event(event.id)
    try:
        source = EventTable.objects.get(pk=table_id, event=event, retired_at__isnull=True)
    except EventTable.DoesNotExist as exc:
        raise NotFound() from exc
    table = _create_table(
        event, source.room, label="", shape=source.shape, width=source.width_m, height=source.height_m,
        x=source.center_x + Decimal("2"), y=source.center_y + Decimal("2"), rotation=source.rotation,
        seats=0, actor=actor, polygon=source.polygon,
    )
    for seat in source.seats.filter(retired_at__isnull=True):
        Seat.objects.create(table=table, label=seat.label, rel_x=seat.rel_x, rel_y=seat.rel_y, orientation=seat.orientation, features=list(seat.features), availability=seat.availability)
    validate_layout(source.room, list(event.tables.filter(retired_at__isnull=True)))
    bump(event, layout=True)
    record(actor=actor, organization=event.organization, event=event, operation="table_duplicated", object_type="table", object_id=table.id, request_id=request_id, before={"source": str(source.id)})
    return table


@transaction.atomic
def update_geometry(*, event, tables, actor, request_id, expected_version, override_reason=""):
    event = lock_event(event.id)
    if event.layout_revision != int(expected_version):
        raise Conflict("stale_version", "Another save landed first. Refresh and try again.", revision=event.layout_revision)
    room = event.rooms.first()
    if room is None:
        raise DomainError("no_room", "Create a room before moving furniture.")
    current = list(EventTable.objects.select_for_update().filter(event=event, retired_at__isnull=True).order_by("id"))
    by_id = {str(table.id): table for table in current}
    for item in tables:
        table = by_id.get(str(item["id"]))
        if table is None:
            raise NotFound("That table is not on this event.")
        if "x" in item:
            table.center_x = quantize(item["x"])
        if "y" in item:
            table.center_y = quantize(item["y"])
        if "rotation" in item:
            table.rotation = quantize(item["rotation"])
        if "label" in item and item["label"] and item["label"] != table.label:
            table.label = str(item["label"]).strip()
    warnings = validate_layout(room, current, override_reason)
    for table in current:
        table.save()
    bump(event, layout=True)
    if warnings:
        record(actor=actor, organization=event.organization, event=event, operation="clearance_override", object_type="room", object_id=room.id, reason=override_reason, request_id=request_id, after={"warnings": warnings})
    record(actor=actor, organization=event.organization, event=event, operation="geometry_updated", object_type="room", object_id=room.id, request_id=request_id)
    return event


@transaction.atomic
def add_chairs(*, event, table_id, count, actor, request_id):
    event = lock_event(event.id)
    try:
        table = EventTable.objects.select_for_update().get(pk=table_id, event=event, retired_at__isnull=True)
    except EventTable.DoesNotExist as exc:
        raise NotFound() from exc
    active = list(table.seats.select_for_update().filter(retired_at__isnull=True))
    active.sort(key=lambda seat: (0, int(seat.label)) if str(seat.label).isdigit() else (1, seat.label))
    offsets = chair_offsets(len(active) + int(count), table.width_m)
    for seat, (rel_x, rel_y, orientation) in zip(active, offsets):
        seat.rel_x = rel_x
        seat.rel_y = rel_y
        seat.orientation = orientation
        seat.save(update_fields=["rel_x", "rel_y", "orientation"])
    seats = []
    start = table.seats.count()
    for index, (rel_x, rel_y, orientation) in enumerate(offsets[len(active):], start=start + 1):
        seats.append(Seat.objects.create(table=table, label=str(index), rel_x=rel_x, rel_y=rel_y, orientation=orientation))
    validate_layout(table.room, list(event.tables.filter(retired_at__isnull=True)))
    from seating.services import cover_new_chair

    for seat in seats:
        cover_new_chair(seat, actor)
    bump(event, layout=True)
    record(actor=actor, organization=event.organization, event=event, operation="chairs_added", object_type="table", object_id=table.id, request_id=request_id, after={"count": len(seats)})
    return seats


@transaction.atomic
def retire_seats(*, event, seat_ids, actor, request_id, resolution=None):
    event = lock_event(event.id)
    seats = list(Seat.objects.select_for_update().filter(pk__in=seat_ids, table__event=event).select_related("table"))
    if len(seats) != len(set(seat_ids)):
        raise NotFound()
    from seating.services import apply_resolution, impacts_for_seats

    if resolution:
        apply_resolution(event, resolution, actor, request_id)
    impacts = impacts_for_seats(seats)
    if impacts["tickets"] or impacts["holds"]:
        raise Conflict("impact_unresolved", "Resolve assigned tickets and holds before removing these seats.", extra={"impacts": impacts})
    now = timezone.now()
    for seat in seats:
        seat.availability = Seat.Availability.RETIRED
        seat.retired_at = now
        seat.save(update_fields=["availability", "retired_at"])
    bump(event, layout=True)
    record(actor=actor, organization=event.organization, event=event, operation="seats_retired", object_type="seat", object_id=seats[0].id if seats else "", request_id=request_id, after={"count": len(seats)})
    return seats


@transaction.atomic
def retire_table(*, event, table_id, actor, request_id, resolution=None):
    event = lock_event(event.id)
    try:
        table = EventTable.objects.select_for_update().get(pk=table_id, event=event, retired_at__isnull=True)
    except EventTable.DoesNotExist as exc:
        raise NotFound() from exc
    seats = list(table.seats.select_for_update().filter(retired_at__isnull=True))
    from seating.services import apply_resolution, impacts_for_seats

    if resolution:
        apply_resolution(event, resolution, actor, request_id)
    impacts = impacts_for_seats(seats)
    if impacts["tickets"] or impacts["holds"]:
        raise Conflict("impact_unresolved", "Resolve assigned tickets and holds before removing this table.", extra={"impacts": impacts})
    now = timezone.now()
    for seat in seats:
        seat.availability = Seat.Availability.RETIRED
        seat.retired_at = now
        seat.save(update_fields=["availability", "retired_at"])
    table.retired_at = now
    table.save(update_fields=["retired_at"])
    bump(event, layout=True)
    record(actor=actor, organization=event.organization, event=event, operation="table_retired", object_type="table", object_id=table.id, request_id=request_id)
    return table


@transaction.atomic
def set_seat_availability(*, event, seat_id, availability, actor, request_id):
    event = lock_event(event.id)
    try:
        seat = Seat.objects.select_for_update().select_related("table").get(pk=seat_id, table__event=event)
    except Seat.DoesNotExist as exc:
        raise NotFound() from exc
    if availability not in {Seat.Availability.ACTIVE, Seat.Availability.BLOCKED}:
        raise DomainError("invalid_availability", "Choose active or blocked.")
    if availability == Seat.Availability.BLOCKED:
        from seating.services import impacts_for_seats

        impacts = impacts_for_seats([seat])
        if impacts["tickets"] or impacts["holds"]:
            raise Conflict("impact_unresolved", "Release this seat before blocking it.", extra={"impacts": impacts})
    seat.availability = availability
    seat.save(update_fields=["availability"])
    bump(event, layout=True)
    record(actor=actor, organization=event.organization, event=event, operation="seat_availability", object_type="seat", object_id=seat.id, request_id=request_id, after={"availability": availability})
    return seat


def layout_payload(event):
    from django.db.models import Prefetch

    from checkin.models import CheckIn
    from guests.models import Ticket
    from layouts.models import Seat
    from seating.models import SeatOccupancy

    room = event.rooms.first()
    tables = []
    assigned = set()
    active_tables = list(event.tables.filter(retired_at__isnull=True).prefetch_related(
        Prefetch("seats", queryset=Seat.objects.filter(retired_at__isnull=True)),
    ))
    seat_ids = [seat.id for table in active_tables for seat in table.seats.all()]
    if seat_ids:
        occupancies = {
            item.seat_id: item
            for item in SeatOccupancy.objects.filter(seat_id__in=seat_ids).select_related("ticket__booking", "hold")
        }
        ticket_ids = [item.ticket_id for item in occupancies.values() if item.ticket_id]
        checked_in_ids = set(
            CheckIn.objects.filter(ticket_id__in=ticket_ids, undone_at__isnull=True).values_list("ticket_id", flat=True)
        ) if ticket_ids else set()
    else:
        occupancies = {}
        checked_in_ids = set()
    for table in active_tables:
        seats = []
        for seat in table.seats.all():
            occupancy = occupancies.get(seat.id)
            occupant = None
            if occupancy and occupancy.ticket_id:
                occupant = {
                    "kind": "ticket",
                    "ticket_id": str(occupancy.ticket_id),
                    "label": occupancy.ticket.display_name,
                    "party": occupancy.ticket.booking.party_name,
                    "checked_in": occupancy.ticket_id in checked_in_ids,
                }
                assigned.add(occupancy.ticket_id)
            elif occupancy and occupancy.hold_id:
                occupant = {"kind": "hold", "hold_id": str(occupancy.hold_id), "purpose": occupancy.hold.purpose}
            seats.append({
                "id": str(seat.id),
                "label": seat.label,
                "rel_x": float(seat.rel_x),
                "rel_y": float(seat.rel_y),
                "availability": seat.availability,
                "features": seat.features,
                "occupancy": occupant,
            })
        tables.append({
            "id": str(table.id),
            "label": table.label,
            "shape": table.shape,
            "width_m": float(table.width_m),
            "height_m": float(table.height_m),
            "x": float(table.center_x),
            "y": float(table.center_y),
            "rotation": float(table.rotation),
            "seats": seats,
        })
    unassigned = []
    for ticket in Ticket.objects.filter(booking__event=event, status=Ticket.Status.ACTIVE).select_related("booking").order_by("booking__party_name", "sequence"):
        if ticket.id in assigned:
            continue
        unassigned.append({
            "ticket_id": str(ticket.id),
            "booking_id": str(ticket.booking_id),
            "party_name": ticket.booking.party_name,
            "email": ticket.booking.original_email,
            "sequence": ticket.sequence,
            "display_name": ticket.display_name,
        })
    return {
        "layout_revision": event.layout_revision,
        "roster_revision": event.roster_revision,
        "republish_required": event.republish_required,
        "room": None if room is None else {"id": str(room.id), "name": room.name, "width_m": float(room.width_m), "height_m": float(room.height_m)},
        "tables": tables,
        "unassigned": unassigned,
    }


def active_capacity(event):
    return Seat.objects.filter(
        table__event=event, table__retired_at__isnull=True, retired_at__isnull=True, availability=Seat.Availability.ACTIVE,
    ).count()
