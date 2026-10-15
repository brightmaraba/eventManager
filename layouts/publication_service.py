from django.db import transaction

from audit.services import record
from core.errors import DomainError
from core.locking import lock_event
from events.models import Event
from guests.models import Ticket
from layouts.models import LayoutPublication
from seating.models import SeatOccupancy


def build_snapshot(event):
    room = event.rooms.first()
    tables = []
    assignments = []
    for table in event.tables.filter(retired_at__isnull=True).prefetch_related("seats"):
        seat_rows = []
        for seat in table.seats.filter(retired_at__isnull=True):
            occupancy = SeatOccupancy.objects.filter(seat=seat).select_related("ticket__booking", "hold").first()
            row = {
                "id": str(seat.id), "label": seat.label, "rel_x": str(seat.rel_x), "rel_y": str(seat.rel_y),
                "availability": seat.availability, "features": seat.features,
            }
            if occupancy and occupancy.ticket_id and occupancy.ticket.status == Ticket.Status.ACTIVE:
                row["occupant"] = "ticket"
                assignments.append({
                    "ticket_id": str(occupancy.ticket_id),
                    "seat_id": str(seat.id),
                    "table_label": table.label,
                    "seat_label": seat.label,
                    "booking_id": str(occupancy.ticket.booking_id),
                    "party_name": occupancy.ticket.booking.party_name,
                    "display_name": occupancy.ticket.display_name,
                })
            elif occupancy and occupancy.hold_id:
                row["occupant"] = "hold"
            seat_rows.append(row)
        tables.append({
            "id": str(table.id), "label": table.label, "shape": table.shape,
            "width_m": str(table.width_m), "height_m": str(table.height_m),
            "x": str(table.center_x), "y": str(table.center_y), "rotation": str(table.rotation),
            "seats": seat_rows,
        })
    assigned_ids = {item["ticket_id"] for item in assignments}
    unassigned = [
        {"ticket_id": str(ticket.id), "booking_id": str(ticket.booking_id), "display_name": ticket.display_name}
        for ticket in Ticket.objects.filter(booking__event=event, status=Ticket.Status.ACTIVE).order_by("sequence")
        if str(ticket.id) not in assigned_ids
    ]
    return {
        "room": None if room is None else {"name": room.name, "width_m": str(room.width_m), "height_m": str(room.height_m)},
        "tables": tables,
        "assignments": assignments,
        "unassigned": unassigned,
        "layout_revision": event.layout_revision,
        "roster_revision": event.roster_revision,
    }


@transaction.atomic
def publish(*, event, actor, request_id, acknowledge_unassigned=False):
    from layouts.geometry import validate_layout

    event = lock_event(event.id)
    room = event.rooms.first()
    if room is None or not event.tables.filter(retired_at__isnull=True).exists():
        raise DomainError("layout_required", "Publish a room that contains at least one table.")
    validate_layout(room, list(event.tables.filter(retired_at__isnull=True)))
    snapshot = build_snapshot(event)
    if snapshot["unassigned"] and not acknowledge_unassigned:
        raise DomainError(
            "unassigned_tickets",
            "Some tickets have no seat. Acknowledge them to publish seating as pending.",
            extra={"unassigned": len(snapshot["unassigned"])},
        )
    number = (event.publications.order_by("-number").values_list("number", flat=True).first() or 0) + 1
    publication = LayoutPublication(
        event=event, number=number, snapshot=snapshot, acknowledged_unassigned=bool(acknowledge_unassigned), created_by=actor,
    )
    publication.save()
    previous_status = event.status
    event.active_publication_id = publication.id
    event.republish_required = False
    if event.status == Event.Status.DRAFT:
        event.status = Event.Status.PUBLISHED
    event.layout_revision += 1
    event.save(update_fields=["active_publication_id", "republish_required", "status", "layout_revision", "updated_at"])
    record(
        actor=actor, organization=event.organization, event=event, operation="layout_published", object_type="publication",
        object_id=publication.id, request_id=request_id, before={"status": previous_status}, after={"number": number},
    )
    return publication


def diff_publications(older, newer):
    def mapping(snapshot):
        return {item["ticket_id"]: item.get("seat_id") for item in snapshot.get("assignments", [])}

    old = mapping(older.snapshot)
    new = mapping(newer.snapshot)
    changed_tickets = {ticket_id for ticket_id in set(old) | set(new) if old.get(ticket_id) != new.get(ticket_id)}
    bookings = set()
    for snapshot in (older.snapshot, newer.snapshot):
        for item in snapshot.get("assignments", []):
            if item["ticket_id"] in changed_tickets:
                bookings.add(item["booking_id"])
        for item in snapshot.get("unassigned", []):
            if item["ticket_id"] in changed_tickets:
                bookings.add(item["booking_id"])
    return sorted(bookings)
