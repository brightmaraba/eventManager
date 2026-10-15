import threading
from datetime import timedelta

import pytest
from django.db import close_old_connections, connections
from django.utils import timezone

from core.errors import Conflict
from guests.models import Booking
from guests.services import get_or_create_booking, set_quantity
from layouts.services import add_chairs
from seating.models import SeatOccupancy
from seating.services import assign, hold_table, swap


def _booking(event, user, email, count=1):
    booking, _created = get_or_create_booking(event=event, email=email, party_name=email)
    set_quantity(event=event, booking=booking, target=count, actor=user, request_id="test")
    return Booking.objects.get(pk=booking.id)


def _race(calls):
    barrier = threading.Barrier(len(calls))
    results = []

    def run(fn):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            results.append(("ok", fn()))
        except Exception as exc:
            results.append(("error", exc))
        finally:
            connections.close_all()

    threads = [threading.Thread(target=run, args=(fn,)) for fn in calls]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return results


@pytest.mark.django_db(transaction=True)
def test_same_seat_assignment_conflicts(owner, event):
    user, _organization = owner
    booking = _booking(event, user, "alex@example.test", 2)
    tickets = list(booking.tickets.order_by("sequence"))
    seat = event.tables.first().seats.order_by("label").first()
    results = _race([
        lambda: assign(event=event, ticket_id=tickets[0].id, seat_id=seat.id, actor=user, request_id="a"),
        lambda: assign(event=event, ticket_id=tickets[1].id, seat_id=seat.id, actor=user, request_id="b"),
    ])
    assert sum(kind == "ok" for kind, _value in results) == 1
    assert any(isinstance(value, Conflict) for kind, value in results if kind == "error")
    assert SeatOccupancy.objects.filter(seat=seat).count() == 1


@pytest.mark.django_db(transaction=True)
def test_one_ticket_cannot_take_two_seats(owner, event):
    user, _organization = owner
    booking = _booking(event, user, "alex@example.test", 1)
    ticket = booking.tickets.get()
    seats = list(event.tables.first().seats.order_by("label")[:2])
    results = _race([
        lambda: assign(event=event, ticket_id=ticket.id, seat_id=seats[0].id, actor=user, request_id="a"),
        lambda: assign(event=event, ticket_id=ticket.id, seat_id=seats[1].id, actor=user, request_id="b"),
    ])
    assert sum(kind == "ok" for kind, _value in results) == 1
    assert SeatOccupancy.objects.filter(ticket=ticket).count() == 1


@pytest.mark.django_db(transaction=True)
def test_table_hold_covers_new_chair(owner, event):
    user, _organization = owner
    table = event.tables.first()

    def hold():
        return hold_table(event=event, table_id=table.id, purpose="VIP", actor=user, request_id="hold")

    def chairs():
        return add_chairs(event=event, table_id=table.id, count=1, actor=user, request_id="chair")

    _race([hold, chairs])
    uncovered = []
    for seat in table.seats.filter(retired_at__isnull=True, availability="active"):
        occupancy = SeatOccupancy.objects.filter(seat=seat).first()
        if occupancy is None or occupancy.hold_id is None:
            uncovered.append(seat.id)
    assert uncovered == []


@pytest.mark.django_db(transaction=True)
def test_expired_hold_can_be_reused_without_beat(owner, event):
    user, _organization = owner
    table = event.tables.first()
    seat = table.seats.order_by("label").first()
    hold_table(event=event, table_id=table.id, purpose="VIP", actor=user, request_id="hold", expires_at=timezone.now() - timedelta(minutes=5))
    booking = _booking(event, user, "alex@example.test", 1)
    assign(event=event, ticket_id=booking.tickets.get().id, seat_id=seat.id, actor=user, request_id="assign")
    occupancy = SeatOccupancy.objects.get(seat=seat)
    assert occupancy.ticket_id == booking.tickets.get().id
    from audit.models import AuditLog

    assert AuditLog.objects.filter(event=event, operation="hold_released", reason="expired").exists()
    assert AuditLog.objects.filter(event=event, operation="seat_assigned").exists()


@pytest.mark.django_db
def test_swap_rolls_back_when_a_seat_is_blocked(owner, event):
    user, _organization = owner
    booking = _booking(event, user, "alex@example.test", 2)
    seats = list(event.tables.first().seats.order_by("label")[:2])
    tickets = list(booking.tickets.order_by("sequence"))
    assign(event=event, ticket_id=tickets[0].id, seat_id=seats[0].id, actor=user, request_id="a")
    assign(event=event, ticket_id=tickets[1].id, seat_id=seats[1].id, actor=user, request_id="b")
    seats[1].availability = "blocked"
    seats[1].save(update_fields=["availability"])
    with pytest.raises(Conflict):
        swap(event=event, seat_a_id=seats[0].id, seat_b_id=seats[1].id, actor=user, request_id="swap")
    assert SeatOccupancy.objects.get(seat=seats[0]).ticket_id == tickets[0].id
    assert SeatOccupancy.objects.get(seat=seats[1]).ticket_id == tickets[1].id
