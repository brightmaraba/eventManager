from pathlib import Path

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from guests.models import Booking, Ticket
from layouts.services import layout_payload
from reports.services import render_html
from seating.services import assign


@pytest.mark.django_db
def test_staff_pages_use_at_most_three_glass_regions(client, owner, event, settings):
    settings.DEBUG = True
    user, _organization = owner
    client.force_login(user)
    responses = [
        client.get("/accounts/login/"),
        client.get("/events/"),
        client.get(f"/events/{event.id}/"),
        client.get(f"/events/{event.id}/layout/"),
        client.get(f"/events/{event.id}/check-ins/"),
    ]
    for response in responses:
        assert response.status_code == 200
        html = response.content.decode()
        assert html.count(" glass") <= 3
        assert "backdrop-filter" not in html


@pytest.mark.django_db
def test_event_detail_glass_is_header_and_metrics_only(client, owner, event, settings):
    settings.DEBUG = True
    user, _organization = owner
    client.force_login(user)
    response = client.get(f"/events/{event.id}/")
    assert response.status_code == 200
    html = response.content.decode()
    assert "site-header glass" in html
    assert "metrics glass" in html
    assert "toolbar glass" not in html


@pytest.mark.django_db
def test_editor_canvas_stays_solid_and_forms_remain(client, owner, event, settings):
    settings.DEBUG = True
    user, _organization = owner
    client.force_login(user)
    response = client.get(f"/events/{event.id}/layout/")
    assert response.status_code == 200
    html = response.content.decode()
    assert 'id="room-canvas"' in html
    assert "toolbar glass" in html
    assert "room-canvas glass" not in html
    assert 'id="add-table"' in html
    assert "Unassign" in html
    assert "Hold table" in html


@pytest.mark.django_db
def test_print_css_is_solid_ink_on_ivory():
    css = Path("reports/static/reports/print.css").read_text(encoding="utf-8")
    assert "backdrop-filter" not in css
    assert "#f5f4ed" in css
    assert "#283113" in css
    assert "overflow-wrap: anywhere" in css


@pytest.mark.django_db
def test_long_names_reach_the_booking_list_and_print_card(owner, event):
    user, _organization = owner
    long_name = "A" * 180
    booking = Booking.objects.create(
        event=event,
        normalized_email="long-name@example.test",
        original_email="long-name@example.test",
        party_name=long_name,
        booking_reference="LONG",
    )
    ticket = Ticket.objects.create(booking=booking, sequence=1, display_name=long_name, status=Ticket.Status.ACTIVE)
    seat = event.tables.filter(retired_at__isnull=True).first().seats.filter(retired_at__isnull=True).first()
    assign(event=event, ticket_id=ticket.id, seat_id=seat.id, actor=user, request_id="ui-long")
    html = render_html(event, "place_cards", public_variant=True, paper="a4", orientation="portrait", fit_mode="fit")
    assert long_name in html
    assert 'class="card"' in html
    assert "backdrop-filter" not in html


@pytest.mark.django_db
def test_layout_payload_query_count_stays_bounded(event):
    with CaptureQueriesContext(connection) as captured:
        payload = layout_payload(event)
    assert len(payload["tables"]) == 10
    assert len(captured) <= 8
