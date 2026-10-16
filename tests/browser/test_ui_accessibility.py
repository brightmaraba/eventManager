import pytest

from guests.models import Booking, Ticket
from guests.tokens import issue_booking_token
from tests.browser.support import assert_no_serious_axe_violations, assert_reflow, login

pytestmark = [pytest.mark.browser, pytest.mark.django_db(transaction=True)]


def test_login_event_editor_checkin_and_import_have_no_serious_axe_violations(page, live_server, owner, event):
    user, _organization = owner
    page.goto(f"{live_server.url}/accounts/login/")
    assert_no_serious_axe_violations(page)
    login(page, live_server, user)
    assert_no_serious_axe_violations(page)
    page.goto(f"{live_server.url}/events/{event.id}/")
    assert page.locator(".glass").count() <= 3
    assert_no_serious_axe_violations(page)
    page.goto(f"{live_server.url}/events/{event.id}/layout/")
    page.wait_for_selector(".table-shape")
    assert page.locator(".glass").count() <= 3
    assert page.locator("#room-canvas.glass").count() == 0
    assert_no_serious_axe_violations(page)
    page.goto(f"{live_server.url}/events/{event.id}/check-ins/")
    assert_no_serious_axe_violations(page)
    page.goto(f"{live_server.url}/events/{event.id}/imports/")
    page.locator("input[name=csv]").set_input_files({
        "name": "guests.csv",
        "mimeType": "text/csv",
        "buffer": b"email,ticket_count,party_name\nada@example.test,1,Ada family\n",
    })
    page.get_by_role("button", name="Preview import").click()
    page.get_by_role("heading", name="Import preview").wait_for()
    assert_no_serious_axe_violations(page)
    page.goto(f"{live_server.url}/events/00000000-0000-0000-0000-000000000000/")
    page.get_by_role("heading", name="Not found.").wait_for()
    assert_no_serious_axe_violations(page)


def test_ordinary_pages_reflow_at_320_css_pixels(page, live_server, owner, event):
    user, _organization = owner
    long_name = "A" * 180
    Booking.objects.create(
        event=event,
        normalized_email="long-name@example.test",
        original_email="long-name@example.test",
        party_name=long_name,
        booking_reference="LONG",
    )
    token = issue_booking_token(
        Booking.objects.get(event=event, normalized_email="long-name@example.test")
    )
    page.set_viewport_size({"width": 320, "height": 800})
    page.goto(f"{live_server.url}/accounts/login/")
    assert page.evaluate("() => document.documentElement.scrollWidth") <= 321
    login(page, live_server, user)
    for path in (
        "/events/",
        f"/events/{event.id}/",
        f"/events/{event.id}/bookings/",
        f"/events/{event.id}/check-ins/",
        f"/guest/{token}/",
    ):
        page.goto(live_server.url + path)
        assert page.evaluate("() => document.documentElement.scrollWidth") <= 321
    page.goto(f"{live_server.url}/events/{event.id}/bookings/")
    assert page.get_by_text(long_name).count() == 1


def test_dragging_a_table_does_not_rebuild_the_canvas(page, live_server, owner, event):
    user, _organization = owner
    login(page, live_server, user)
    page.goto(f"{live_server.url}/events/{event.id}/layout/")
    page.wait_for_selector(".table-shape")
    page.evaluate(
        """() => {
          const canvas = document.querySelector("#room-canvas");
          const original = canvas.replaceChildren.bind(canvas);
          canvas.replaceChildren = (...args) => {
            canvas.dataset.rebuilds = String(Number(canvas.dataset.rebuilds || 0) + 1);
            return original(...args);
          };
          canvas.dataset.rebuilds = "0";
        }"""
    )
    box = page.locator(".table-shape").first.bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] / 2 + 48, box["y"] + box["height"] / 2 + 24, steps=6)
    transform = page.evaluate("() => document.querySelector('#room-canvas [data-table-id]').getAttribute('transform')")
    rebuilds = page.evaluate("() => document.querySelector('#room-canvas').dataset.rebuilds")
    # Wait for the save so teardown does not truncate tables while the live server is mid-request.
    with page.expect_response(lambda response: response.request.method == "PATCH" and "layout.json" in response.url):
        page.mouse.up()
    assert transform is not None and transform.startswith("translate")
    assert rebuilds == "0"


def test_public_seating_keeps_pending_copy(page, live_server, event):
    booking = Booking.objects.create(
        event=event,
        normalized_email="guest@example.test",
        original_email="guest@example.test",
        party_name="Ada family",
        booking_reference="ADA",
    )
    Ticket.objects.create(booking=booking, sequence=1, display_name="Ada", status=Ticket.Status.ACTIVE)
    token = issue_booking_token(booking)
    page.goto(f"{live_server.url}/guest/{token}/")
    assert page.get_by_text("Your seating is still pending.").count() == 1
    assert page.locator(".glass").count() <= 3
    assert_reflow(page)
