import pytest
from django.core.cache import cache
from django.db import connection

from communications.services import create_campaign, dispatch_pending, queue_campaign
from core.errors import Conflict
from guests.services import get_or_create_booking, set_quantity
from layouts.services import retire_table, update_geometry
from reports.services import html_to_pdf, render_html
from seating.services import assign


@pytest.mark.django_db
def test_occupied_table_retirement_reports_impact(owner, event):
    user, _organization = owner
    booking, _created = get_or_create_booking(event=event, email="guest@example.test", party_name="Guest")
    set_quantity(event=event, booking=booking, target=1, actor=user, request_id="test")
    table = event.tables.order_by("label").first()
    seat = table.seats.order_by("label").first()
    assign(event=event, ticket_id=booking.tickets.get().id, seat_id=seat.id, actor=user, request_id="test")
    with pytest.raises(Conflict) as caught:
        retire_table(event=event, table_id=table.id, actor=user, request_id="test")
    assert caught.value.extra["impacts"]["tickets"]
    table.refresh_from_db()
    assert table.retired_at is None


@pytest.mark.django_db
def test_moving_a_table_keeps_seat_ids(owner, event):
    user, _organization = owner
    table = event.tables.order_by("label").first()
    before = list(table.seats.order_by("id").values_list("id", flat=True))
    event.refresh_from_db()
    update_geometry(
        event=event,
        tables=[{"id": str(table.id), "x": float(table.center_x) + 0.5, "y": float(table.center_y)}],
        actor=user,
        request_id="test",
        expected_version=event.layout_revision,
    )
    table.refresh_from_db()
    assert list(table.seats.order_by("id").values_list("id", flat=True)) == before
    assert float(table.center_x) > 2.5


@pytest.mark.django_db
def test_clearing_the_broker_does_not_drop_pending_mail(owner, event, settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    user, _organization = owner
    booking, _created = get_or_create_booking(event=event, email="guest@example.test")
    set_quantity(event=event, booking=booking, target=1, actor=user, request_id="test")
    campaign = create_campaign(
        event=event, actor=user, kind="invitation", subject="Join us", audience_filter={"kind": "all"}, request_id="test",
    )
    queue_campaign(campaign=campaign, actor=user, request_id="test")
    cache.clear()
    from communications.models import EmailDelivery

    assert EmailDelivery.objects.filter(state="pending").count() == 1
    dispatch_pending()
    assert EmailDelivery.objects.filter(state="submitted").count() == 1


@pytest.mark.django_db
def test_weasyprint_pdf_and_public_html(owner, event):
    html = render_html(event, "room_plan", public_variant=True, paper="a3", orientation="landscape", fit_mode="fit")
    assert "guest@" not in html
    pdf = html_to_pdf(html)
    assert pdf.startswith(b"%PDF")


@pytest.mark.django_db(transaction=True)
def test_runtime_database_role_cannot_create_tables():
    import psycopg

    from core.dbroles import provision

    settings = connection.settings_dict
    admin = (
        f"host={settings['HOST']} port={settings['PORT']} dbname={settings['NAME']} "
        f"user={settings['USER']} password={settings['PASSWORD']}"
    )
    app = (
        f"host={settings['HOST']} port={settings['PORT']} dbname={settings['NAME']} "
        "user=pytest_app password=pytest-app-pass"
    )
    provision(
        admin,
        database=settings["NAME"],
        migrate_role="pytest_migrate",
        migrate_password="pytest-migrate-pass",
        app_role="pytest_app",
        app_password="pytest-app-pass",
    )
    try:
        with psycopg.connect(app, autocommit=True) as runtime:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                runtime.execute("CREATE TABLE pytest_privilege_probe (id integer)")
    finally:
        with psycopg.connect(admin, autocommit=True) as admin_connection:
            admin_connection.execute("DROP OWNED BY pytest_app")
            admin_connection.execute("DROP OWNED BY pytest_migrate")
            admin_connection.execute("DROP ROLE IF EXISTS pytest_app")
            admin_connection.execute("DROP ROLE IF EXISTS pytest_migrate")
