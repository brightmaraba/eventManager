import pytest

from core.errors import Conflict, DomainError
from guests.imports import commit_import, preview_import
from guests.models import Ticket
from guests.services import set_quantity
from seating.services import assign


def _import(event, user, raw, **kwargs):
    batch = preview_import(event=event, actor=user, raw=raw, filename="guests.csv", request_id="test", **kwargs)
    if batch.state == "committed":
        return batch
    return commit_import(event=event, batch=batch, actor=user, request_id="test")


@pytest.mark.django_db
def test_import_creates_stable_tickets_and_repeat_does_not_double(owner, event):
    user, _organization = owner
    raw = b"email,ticket_count,party_name\nalex@example.test,4,Alex family\n"
    first = _import(event, user, raw)
    tickets = list(Ticket.objects.filter(booking__event=event, status="active").order_by("sequence"))
    assert len(tickets) == 4
    assert [ticket.sequence for ticket in tickets] == [1, 2, 3, 4]
    second = _import(event, user, raw)
    assert second.id == first.id
    assert Ticket.objects.filter(booking__event=event, status="active").count() == 4
    assert set(Ticket.objects.filter(booking__event=event).values_list("id", flat=True)) == {ticket.id for ticket in tickets}


@pytest.mark.django_db
def test_invalid_import_does_not_partially_commit(owner, event):
    user, _organization = owner
    raw = b"email,ticket_count\nnot-an-email,2\nsam@example.test,0\n"
    batch = preview_import(event=event, actor=user, raw=raw, filename="bad.csv", request_id="test")
    with pytest.raises(DomainError):
        commit_import(event=event, batch=batch, actor=user, request_id="test")
    assert event.bookings.count() == 0


@pytest.mark.django_db
def test_duplicate_rows_and_unsupported_column(owner, event):
    user, _organization = owner
    raw = b"email,ticket_count\nalex@example.test,1\nalex@example.test,2\n"
    batch = preview_import(event=event, actor=user, raw=raw, filename="dup.csv", request_id="test")
    assert batch.rows.exclude(errors=[]).exists()
    with pytest.raises(DomainError):
        preview_import(event=event, actor=user, raw=b"email,ticket_count,attendee_names\na@example.test,1,Ann\n", filename="names.csv", request_id="test")


@pytest.mark.django_db
def test_quantity_drop_cannot_remove_assigned_ticket(owner, event):
    user, _organization = owner
    _import(event, user, b"email,ticket_count,party_name\nalex@example.test,4,Alex family\n")
    booking = event.bookings.get()
    ticket = booking.tickets.order_by("sequence").first()
    seat = event.tables.first().seats.first()
    assign(event=event, ticket_id=ticket.id, seat_id=seat.id, actor=user, request_id="test")
    with pytest.raises(Conflict):
        set_quantity(event=event, booking=booking, target=0, actor=user, request_id="test")
    ticket.refresh_from_db()
    assert ticket.status == "active"


@pytest.mark.django_db
def test_stale_preview_conflicts(owner, event):
    user, _organization = owner
    batch = preview_import(event=event, actor=user, raw=b"email,ticket_count\nalex@example.test,1\n", filename="a.csv", request_id="test")
    event.roster_revision = 9
    event.save(update_fields=["roster_revision"])
    with pytest.raises(Conflict):
        commit_import(event=event, batch=batch, actor=user, request_id="test")


@pytest.mark.django_db
def test_absence_from_import_does_not_delete_booking(owner, event):
    user, _organization = owner
    _import(event, user, b"email,ticket_count\nalex@example.test,2\nsam@example.test,1\n")
    _import(event, user, b"email,ticket_count\nalex@example.test,2\n", force_new=True)
    assert event.bookings.count() == 2
    assert event.bookings.get(normalized_email="sam@example.test").tickets.filter(status="active").count() == 1
