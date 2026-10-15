import base64
import json
import time

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from communications.models import Campaign, CampaignAudience, EmailDelivery, ProviderEvent
from communications.webhooks import apply_events, verify_signature
from core.errors import DomainError
from guests.services import get_or_create_booking, set_quantity


def _delivery(owner, event):
    user, _organization = owner
    booking, _created = get_or_create_booking(event=event, email="guest@example.test")
    set_quantity(event=event, booking=booking, target=1, actor=user, request_id="test")
    campaign = Campaign.objects.create(event=event, kind="invitation", subject="Hello", created_by=user, status="sending")
    audience = CampaignAudience.objects.create(campaign=campaign, booking_ids=[str(booking.id)])
    return EmailDelivery.objects.create(
        audience=audience, booking=booking, recipient_email=booking.original_email, subject="Hello",
        text_body="Hello", html_body="<p>Hello</p>", state="submitted",
    )


def _signed(payload, private_key):
    timestamp = str(int(time.time()))
    signature = base64.b64encode(private_key.sign(timestamp.encode() + payload, ec.ECDSA(hashes.SHA256()))).decode()
    public = base64.b64encode(
        private_key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    ).decode()
    return public, timestamp, signature


@pytest.mark.django_db
def test_webhook_rejects_bad_signatures_and_deduplicates(owner, event, settings):
    delivery = _delivery(owner, event)
    private_key = ec.generate_private_key(ec.SECP256R1())
    payload = json.dumps([{"sg_event_id": "evt-1", "event": "delivered", "delivery_id": str(delivery.id)}]).encode()
    public, timestamp, signature = _signed(payload, private_key)
    settings.SENDGRID_WEBHOOK_PUBLIC_KEY = public
    with pytest.raises(DomainError):
        verify_signature(payload, "not-a-signature", timestamp)
    delivery.refresh_from_db()
    assert delivery.state == "submitted"
    verify_signature(payload, signature, timestamp)
    assert apply_events(json.loads(payload)) == 1
    delivery.refresh_from_db()
    assert delivery.state == "delivered"
    assert apply_events(json.loads(payload)) == 0
    assert ProviderEvent.objects.count() == 1


@pytest.mark.django_db
def test_bounce_is_not_overwritten_by_a_late_delivery(owner, event):
    delivery = _delivery(owner, event)
    apply_events([{"sg_event_id": "bounce-1", "event": "bounce", "delivery_id": str(delivery.id)}])
    apply_events([{"sg_event_id": "delivered-late", "event": "delivered", "delivery_id": str(delivery.id)}])
    delivery.refresh_from_db()
    assert delivery.state == "bounced"


@pytest.mark.django_db
def test_complaint_suppresses_later_sends(owner, event, settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    delivery = _delivery(owner, event)
    apply_events([{"sg_event_id": "spam-1", "event": "spamreport", "delivery_id": str(delivery.id)}])
    from communications.services import create_campaign, dispatch_pending, queue_campaign

    user = owner[0]
    campaign = create_campaign(event=event, actor=user, kind="invitation", subject="Again", audience_filter={"kind": "all"}, request_id="test")
    queue_campaign(campaign=campaign, actor=user, request_id="test")
    dispatch_pending()
    assert EmailDelivery.objects.filter(audience__campaign=campaign, state="suppressed").exists()
