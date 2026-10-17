import pytest

from accounts.models import EventGrant
from communications.models import EmailDelivery
from guests.gala import CAMPAIGN_SUBJECT
from guests.services import get_or_create_booking


@pytest.mark.django_db
def test_door_shows_totals_scanner_and_send(client, owner, event, settings):
    settings.DEBUG = True
    user, _organization = owner
    client.force_login(user)
    blocked = client.get(f"/events/{event.id}/check-ins/")
    assert blocked.status_code == 200
    blocked_html = blocked.content.decode()
    assert "Door totals" in blocked_html
    assert 'id="scan-video"' in blocked_html
    assert 'id="scan-start"' in blocked_html
    assert "Set PUBLIC_BASE_URL" in blocked_html
    assert ">Send</button>" not in blocked_html
    assert blocked_html.count(" glass") <= 3
    settings.PUBLIC_BASE_URL = "https://libranconsult.tech"
    settings.EMAIL_HOST = "smtp.sendgrid.net"
    settings.EMAIL_HOST_PASSWORD = "secret"
    settings.DEFAULT_FROM_EMAIL = "Kokwet NSW Association <postmaster@communitycore.com.au>"
    get_or_create_booking(event=event, email="guest@example.test", actor=user, request_id="door")
    ready = client.get(f"/events/{event.id}/check-ins/")
    assert ">Send</button>" in ready.content.decode()


@pytest.mark.django_db
def test_checkin_staff_can_scan_and_cannot_send(client, owner, event):
    _user, _organization = owner
    staff = owner[0].__class__.objects.create_user("door-staff@example.test", "S3cure-pass-word")
    EventGrant.objects.create(user=staff, event=event, role=EventGrant.Role.CHECKIN_STAFF)
    client.force_login(staff)
    response = client.get(f"/events/{event.id}/check-ins/")
    html = response.content.decode()
    assert response.status_code == 200
    assert 'id="scan-start"' in html
    assert ">Send</button>" not in html


@pytest.mark.django_db
def test_send_waits_for_confirmation(client, owner, event, settings):
    settings.DEBUG = True
    user, _organization = owner
    get_or_create_booking(event=event, email="guest@example.test", actor=user, request_id="door")
    settings.PUBLIC_BASE_URL = "https://libranconsult.tech"
    settings.EMAIL_HOST = "smtp.sendgrid.net"
    settings.EMAIL_HOST_PASSWORD = "secret"
    settings.DEFAULT_FROM_EMAIL = "Kokwet NSW Association <postmaster@communitycore.com.au>"
    client.force_login(user)
    response = client.post(f"/events/{event.id}/check-ins/", {"action": "send"})
    assert response.status_code == 200
    assert b"Tick the confirmation" in response.content
    assert EmailDelivery.objects.count() == 0


@pytest.mark.django_db
def test_send_queues_every_guest(client, owner, event, settings):
    settings.DEBUG = True
    user, _organization = owner
    get_or_create_booking(event=event, email="guest@example.test", actor=user, request_id="door")
    settings.PUBLIC_BASE_URL = "https://libranconsult.tech"
    settings.EMAIL_HOST = "smtp.sendgrid.net"
    settings.EMAIL_HOST_PASSWORD = "secret"
    settings.DEFAULT_FROM_EMAIL = "Kokwet NSW Association <postmaster@communitycore.com.au>"
    client.force_login(user)
    response = client.post(
        f"/events/{event.id}/check-ins/",
        {"action": "send", "confirm": "yes"},
    )
    assert response.status_code == 302
    campaign = event.campaigns.get(subject=CAMPAIGN_SUBJECT)
    assert campaign.status == "sending"
    delivery = EmailDelivery.objects.get()
    assert delivery.recipient_email == "guest@example.test"
    assert delivery.state == "pending"


@pytest.mark.django_db
def test_home_opens_the_gala_door(client, owner, event, settings):
    settings.DEBUG = True
    user, _organization = owner
    event.slug = "kacw-gala-night"
    event.save(update_fields=["slug"])
    client.force_login(user)
    response = client.get("/")
    assert response.status_code == 302
    assert response.url == f"/events/{event.id}/check-ins/"
