import base64
import time

from django.conf import settings
from django.db import IntegrityError, transaction

from communications.models import EmailDelivery, ProviderEvent, Suppression
from core.errors import DomainError
from guests.services import normalize_email


def verify_signature(payload, signature, timestamp, public_key=None):
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    public_key = public_key if public_key is not None else settings.SENDGRID_WEBHOOK_PUBLIC_KEY
    if not public_key or not signature or timestamp in (None, ""):
        raise DomainError("invalid_signature", "The webhook signature is missing.", status=403)
    try:
        stamp = int(timestamp)
    except (TypeError, ValueError) as exc:
        raise DomainError("invalid_signature", "The webhook timestamp is invalid.", status=403) from exc
    if abs(int(time.time()) - stamp) > settings.WEBHOOK_TIMESTAMP_TOLERANCE:
        raise DomainError("stale_signature", "The webhook timestamp is outside the allowed window.", status=403)
    try:
        if "BEGIN PUBLIC KEY" in public_key:
            key = serialization.load_pem_public_key(public_key.encode())
        else:
            key = serialization.load_der_public_key(base64.b64decode(public_key))
        key.verify(base64.b64decode(signature), str(timestamp).encode() + payload, ec.ECDSA(hashes.SHA256()))
    except (InvalidSignature, ValueError, TypeError) as exc:
        raise DomainError("invalid_signature", "The webhook signature could not be verified.", status=403) from exc


def _redact_event(event):
    cleaned = dict(event)
    cleaned.pop("email", None)
    return cleaned


@transaction.atomic
def apply_events(events):
    effects = 0
    for event in events:
        provider_id = str(event.get("sg_event_id") or "")
        if not provider_id:
            raise DomainError("invalid_payload", "Each event needs an sg_event_id.")
        delivery = None
        delivery_id = (event.get("delivery_id") or "")
        if delivery_id:
            delivery = EmailDelivery.objects.filter(pk=delivery_id).first()
        try:
            with transaction.atomic():
                ProviderEvent.objects.create(
                    provider_event_id=provider_id,
                    delivery=delivery,
                    event_type=str(event.get("event", "")),
                    payload=_redact_event(event),
                )
        except IntegrityError:
            continue
        if delivery is None:
            continue
        kind = event.get("event")
        if kind in {"bounce", "dropped"}:
            if delivery.state != EmailDelivery.State.SUPPRESSED:
                delivery.state = EmailDelivery.State.BOUNCED
                delivery.save(update_fields=["state", "updated_at"])
                effects += 1
        elif kind == "spamreport":
            Suppression.objects.get_or_create(
                organization=delivery.booking.event.organization,
                normalized_email=normalize_email(delivery.recipient_email),
                defaults={"reason": "complaint"},
            )
            delivery.state = EmailDelivery.State.SUPPRESSED
            delivery.save(update_fields=["state", "updated_at"])
            effects += 1
        elif kind == "delivered":
            if delivery.state not in {EmailDelivery.State.BOUNCED, EmailDelivery.State.SUPPRESSED, EmailDelivery.State.FAILED}:
                delivery.state = EmailDelivery.State.DELIVERED
                delivery.save(update_fields=["state", "updated_at"])
                effects += 1
    return effects
