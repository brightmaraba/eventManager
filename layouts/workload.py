import math
from decimal import Decimal

from guests.models import Booking, Ticket
from layouts.geometry import chair_offsets
from layouts.models import EventTable, Seat
from layouts.services import ensure_room


def build_reference_workload(event, *, tables=1000, seats_per_table=10):
    """Create a large unassigned layout for editor measurement. Not used by seed_demo."""
    room = ensure_room(event)
    columns = 40
    spacing = Decimal("4")
    row_count = math.ceil(tables / columns)
    room.width_m = spacing * columns + Decimal("4")
    room.height_m = spacing * row_count + Decimal("4")
    room.save(update_fields=["width_m", "height_m"])
    offsets = chair_offsets(seats_per_table, Decimal("1.6"))
    table_rows = []
    for index in range(tables):
        row, column = divmod(index, columns)
        table_rows.append(EventTable(
            event=event,
            room=room,
            label=f"R{index + 1}",
            shape=EventTable.Shape.ROUND,
            width_m=Decimal("1.600"),
            height_m=Decimal("1.600"),
            center_x=Decimal("2.500") + spacing * column,
            center_y=Decimal("2.500") + spacing * row,
            rotation=Decimal("0"),
        ))
    EventTable.objects.bulk_create(table_rows, batch_size=200)
    seat_rows = []
    for table in table_rows:
        for number, (rel_x, rel_y, orientation) in enumerate(offsets, start=1):
            seat_rows.append(Seat(
                table=table,
                label=str(number),
                rel_x=rel_x,
                rel_y=rel_y,
                orientation=orientation,
            ))
    Seat.objects.bulk_create(seat_rows, batch_size=1000)
    bookings = [
        Booking(
            event=event,
            normalized_email=f"reference-{index + 1:04d}@example.test",
            original_email=f"reference-{index + 1:04d}@example.test",
            party_name=f"Reference party {index + 1}",
            booking_reference=f"REF{index + 1:04d}",
        )
        for index in range(tables)
    ]
    Booking.objects.bulk_create(bookings, batch_size=200)
    ticket_rows = []
    for booking in bookings:
        for sequence in range(1, seats_per_table + 1):
            ticket_rows.append(Ticket(
                booking=booking,
                sequence=sequence,
                display_name=f"Guest {sequence}",
                status=Ticket.Status.ACTIVE,
            ))
    Ticket.objects.bulk_create(ticket_rows, batch_size=1000)
    return {"tables": tables, "tickets": tables * seats_per_table}
