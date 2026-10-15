import pytest

from checkin.models import CheckIn
from checkin.services import check_in, undo_check_in
from core.errors import Conflict
from guests.services import cancel_ticket, get_or_create_booking, set_quantity
from guests.tokens import issue_booking_token, resolve_token
from reports.services import assignments_csv, render_html


@pytest.mark.django_db
def test_check_in_is_idempotent_and_rejects_cancelled_tickets(owner, event):
    user, _organization = owner
    booking, _created = get_or_create_booking(event=event, email="party@example.test", party_name="Party")
    set_quantity(event=event, booking=booking, target=4, actor=user, request_id="test")
    tickets = list(booking.tickets.order_by("sequence"))
    first = check_in(event=event, ticket_id=tickets[0].id, actor=user, request_id="a")
    second = check_in(event=event, ticket_id=tickets[0].id, actor=user, request_id="b")
    assert second["already_checked_in"] is True
    assert second["checked_in_at"] == first["checked_in_at"]
    assert CheckIn.objects.filter(ticket=tickets[0]).count() == 1
    check_in(event=event, ticket_id=tickets[1].id, actor=user, request_id="c")
    from checkin.services import party_progress

    assert party_progress(booking) == {"arrived": 2, "total": 4}
    undo_check_in(event=event, ticket_id=tickets[1].id, actor=user, request_id="undo", reason="wrong guest")
    assert party_progress(booking)["arrived"] == 1
    cancel_ticket(event=event, ticket=tickets[2], actor=user, request_id="cancel", reason="no show")
    with pytest.raises(Conflict):
        check_in(event=event, ticket_id=tickets[2].id, actor=user, request_id="nope")


@pytest.mark.django_db
def test_guest_token_cannot_read_another_booking(owner, event):
    user, _organization = owner
    first, _created = get_or_create_booking(event=event, email="one@example.test")
    second, _unused = get_or_create_booking(event=event, email="two@example.test")
    set_quantity(event=event, booking=first, target=1, actor=user, request_id="test")
    set_quantity(event=event, booking=second, target=1, actor=user, request_id="test")
    raw = issue_booking_token(first)
    token = resolve_token(raw, "booking_view")
    assert token.booking_id == first.id
    assert resolve_token(raw, "checkin") is None


@pytest.mark.django_db
def test_public_export_hides_email_and_csv_escapes_formulas(owner, event):
    user, _organization = owner
    booking, _created = get_or_create_booking(event=event, email="guest@example.test", party_name="=SUM(1,1)")
    set_quantity(event=event, booking=booking, target=1, actor=user, request_id="test")
    from layouts.publication_service import publish

    publish(event=event, actor=user, request_id="test", acknowledge_unassigned=True)
    html = render_html(event, "alpha_roster", public_variant=True)
    assert "guest@example.test" not in html
    assert "=SUM" not in assignments_csv(event, include_email=False, actor=user).split("party_name", 1)[-1] or "'" in assignments_csv(event, include_email=False, actor=user)
    csv_text = assignments_csv(event, include_email=True, actor=user)
    assert "'=SUM(1,1)" in csv_text


@pytest.mark.django_db
def test_logs_redact_email_and_tokens():
    from core.logging import redact

    text = redact("sent to guest@example.test via /guest/abcDEF123_token-value/")
    assert "guest@example.test" not in text
    assert "abcDEF123" not in text
