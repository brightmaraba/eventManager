import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from accounts.models import EventGrant, Membership, User
from core.errors import Conflict, DomainError
from events.services import change_status, parse_local_datetime, save_image
from layouts.models import Seat
from layouts.services import active_capacity, add_chairs


@pytest.mark.django_db
def test_new_table_finds_open_space(owner, event):
    from layouts.services import create_table

    user, _organization = owner
    table = create_table(event=event, actor=user, request_id="test", seats=8)
    assert table.label == "T11"
    assert active_capacity(event) == 88


@pytest.mark.django_db
def test_ten_tables_then_two_chairs(owner, event):
    user, _organization = owner
    assert active_capacity(event) == 80
    table = event.tables.first()
    add_chairs(event=event, table_id=table.id, count=2, actor=user, request_id="test")
    assert active_capacity(event) == 82
    assert Seat.objects.filter(table__event=event, retired_at__isnull=True).count() == 82


@pytest.mark.django_db
def test_archive_is_reversible_and_gap_time_is_rejected(owner, event):
    user, _organization = owner
    change_status(actor=user, event=event, action="archive", reason="", request_id="test")
    event.refresh_from_db()
    assert event.status == "archived"
    change_status(actor=user, event=event, action="unarchive", reason="", request_id="test")
    event.refresh_from_db()
    assert event.status == "draft"
    with pytest.raises(DomainError):
        parse_local_datetime("2026-03-08T02:30", "America/New_York")
    stored = parse_local_datetime("2026-07-01T18:00", "America/New_York")
    assert stored.hour == 22


@pytest.mark.django_db
def test_svg_logo_is_rejected(owner, event):
    user, _organization = owner
    upload = SimpleUploadedFile("logo.svg", b"<svg xmlns='http://www.w3.org/2000/svg'></svg>", content_type="image/svg+xml")
    with pytest.raises(DomainError):
        save_image(actor=user, event=event, uploaded=upload, field="logo", request_id="test")


@pytest.mark.django_db
def test_png_logo_is_reencoded(owner, event):
    user, _organization = owner
    buffer = io.BytesIO()
    Image.new("RGB", (20, 10), "white").save(buffer, format="PNG")
    upload = SimpleUploadedFile("logo.png", buffer.getvalue(), content_type="image/png")
    save_image(actor=user, event=event, uploaded=upload, field="logo", request_id="test")
    event.refresh_from_db()
    assert event.logo.name.endswith(".png")


@pytest.mark.django_db
def test_cross_tenant_and_role_limits(client, owner, event):
    _owner, organization = owner
    other = User.objects.create_user("other@example.test", "S3cure-pass-word")
    other_org = organization.__class__.objects.create(name="Other", slug="other")
    Membership.objects.create(user=other, organization=other_org, role=Membership.Role.OWNER)
    from django_otp import DEVICE_ID_SESSION_KEY
    from django_otp.plugins.otp_totp.models import TOTPDevice

    device = TOTPDevice.objects.create(user=other, name="test", confirmed=True)
    client.force_login(other)
    session = client.session
    session[DEVICE_ID_SESSION_KEY] = device.persistent_id
    session.save()
    hidden = client.get(f"/events/{event.id}/")
    assert hidden.status_code == 404
    staff = User.objects.create_user("door@example.test", "S3cure-pass-word")
    EventGrant.objects.create(user=staff, event=event, role=EventGrant.Role.CHECKIN_STAFF)
    client.force_login(staff)
    assert client.get(f"/events/{event.id}/").status_code == 200
    response = client.post(f"/events/{event.id}/tables/", {"seats": 4})
    assert response.status_code == 403


@pytest.mark.django_db
def test_production_login_requires_mfa(client, owner, settings):
    settings.DEBUG = False
    response = client.post("/accounts/login/", {"email": "owner@example.test", "password": "S3cure-pass-word"})
    assert response.status_code == 302
    assert response.url.endswith("/accounts/mfa/enroll/")
    blocked = client.get("/events/")
    assert blocked.status_code == 302
    assert "/accounts/login/" in blocked.url


@pytest.mark.django_db
def test_idempotency_replay_and_mismatch(owner, event):
    from core.idempotency import execute
    from events.services import update_event

    user, organization = owner

    def run(name):
        def fn():
            update_event(actor=user, event=event, data={"name": name}, request_id="test")
            event.refresh_from_db()
            return {"name": event.name}

        return fn

    first = execute(organization=organization, operation="rename", key="same-key", payload={"name": "One"}, fn=run("One"))
    second = execute(organization=organization, operation="rename", key="same-key", payload={"name": "One"}, fn=run("Ignored"))
    assert second.replayed is True
    assert second.body["name"] == "One"
    event.refresh_from_db()
    assert event.name == "One"
    with pytest.raises(Conflict):
        execute(organization=organization, operation="rename", key="same-key", payload={"name": "Two"}, fn=run("Two"))
    assert first.body["name"] == "One"
