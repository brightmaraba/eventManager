import pytest

from communications.provider import inline_images
from communications.rendering import render_message
from communications.services import create_campaign
from events.services import create_event
from guests.gala import (
    assign_parties,
    group_payment_rows,
    import_payments,
    place_tables,
    publish_gala,
    smtp_problems,
    ticket_codes,
    ticket_quantity,
)
from guests.models import Ticket
from layouts.models import EventTable
from seating.models import SeatOccupancy


def test_ticket_price_counts_seats():
    assert ticket_quantity("") == 1
    assert ticket_quantity("100") == 1
    assert ticket_quantity("300") == 3
    assert ticket_codes("TKT-0001", 1) == ["TKT-0001"]
    assert ticket_codes("TKT-0001", 2) == ["TKT-0001", "TKT-0001-2"]


def test_blank_stripe_ids_are_not_one_party():
    rows = [
        {"email": "a@example.test", "stripe_id": "", "ticket_number": "TKT-1", "amount": ""},
        {"email": "b@example.test", "stripe_id": "", "ticket_number": "TKT-2", "amount": ""},
    ]
    assert len(group_payment_rows(rows)) == 2
    shared = [
        {"email": "a@example.test", "stripe_id": "ch_shared", "ticket_number": "TKT-1", "amount": "100"},
        {"email": "b@example.test", "stripe_id": "ch_shared", "ticket_number": "TKT-2", "amount": "100"},
    ]
    assert len(group_payment_rows(shared)) == 1


def test_smtp_is_not_ready_for_local_mail(settings):
    settings.PUBLIC_BASE_URL = "http://localhost:8000"
    settings.EMAIL_HOST = "maildev"
    settings.EMAIL_HOST_PASSWORD = ""
    settings.DEFAULT_FROM_EMAIL = "events@example.test"
    assert smtp_problems()


@pytest.mark.django_db
def test_payment_rows_share_a_table_and_email_a_ticket(owner, settings):
    settings.PUBLIC_BASE_URL = "https://tickets.example.test"
    user, organization = owner
    event = create_event(
        actor=user,
        organization=organization,
        data={
            "name": "Gala fixture",
            "venue_name": "Hall",
            "address_line1": "1 Street",
            "locality": "Fairfield Heights",
            "postal_code": "2165",
            "country": "Australia",
            "timezone": "Australia/Sydney",
            "starts_at": "2026-10-17T17:00",
            "ends_at": "2026-10-17T22:00",
            "doors_open_at": "2026-10-17T16:30",
            "initial_table_count": 0,
            "default_seats_per_table": 2,
        },
        request_id="test",
    )
    rows = [
        {"payment_id": "PAY-1", "ticket_number": "TKT-0001", "source": "Stripe payment", "stripe_id": "ch_a", "amount": "200", "email": "a@example.test"},
        {"payment_id": "PAY-2", "ticket_number": "TKT-0002", "source": "Stripe payment", "stripe_id": "ch_shared", "amount": "100", "email": "b@example.test"},
        {"payment_id": "PAY-3", "ticket_number": "TKT-0003", "source": "Stripe payment", "stripe_id": "ch_shared", "amount": "100", "email": "c@example.test"},
    ]
    imported = import_payments(event, user, rows, "test")
    assert imported["created"] == 4
    assert import_payments(event, user, rows, "test")["unchanged"] is True
    assert Ticket.objects.filter(booking__event=event).count() == 4
    place_tables(event, user, "test", table_count=3, seats=2)
    assign_parties(event, user, rows, "test")
    publication = publish_gala(event, user, "test")

    codes = set(Ticket.objects.filter(booking__event=event).values_list("public_code", flat=True))
    assert codes == {"TKT-0001", "TKT-0001-2", "TKT-0002", "TKT-0003"}
    party_tables = set(
        Ticket.objects.filter(booking__normalized_email="a@example.test").values_list("occupancy__seat__table__label", flat=True)
    )
    shared_tables = set(
        Ticket.objects.filter(booking__normalized_email__in=["b@example.test", "c@example.test"]).values_list(
            "occupancy__seat__table__label", flat=True
        )
    )
    assert party_tables == {"2"} or party_tables == {"3"}
    assert len(shared_tables) == 1
    assert party_tables != shared_tables
    assert "1" not in party_tables
    reserved = EventTable.objects.get(event=event, label="1")
    assert SeatOccupancy.objects.filter(seat__table=reserved, ticket__isnull=False).count() == 0
    assert SeatOccupancy.objects.filter(seat__table=reserved, hold__isnull=False).count() == 2

    booking = event.bookings.get(normalized_email="a@example.test")
    campaign = create_campaign(
        event=event, actor=user, kind="seating", subject="Your ticket", audience_filter={"kind": "all"}, request_id="test"
    )
    _subject, html, text = render_message(campaign, booking, publication, issue_link=True)
    assert "TKT-0001" in html
    assert "TKT-0001-2" in html
    assert "/checkin/t/" in html
    assert "TKT-0001" in text
    images = inline_images(html)
    assert images[0][0] == "kcaw-logo"
    assert images[0][1].startswith(b"\x89PNG")
    assert any(name.startswith("qr-") and payload.startswith(b"\x89PNG") for name, payload, _filename in images)
