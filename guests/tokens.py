import hashlib
import secrets
from datetime import timedelta

from django.utils import timezone

from guests.models import AccessToken


def _hash(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


def issue_booking_token(booking, days=90):
    raw = secrets.token_urlsafe(32)
    AccessToken.objects.create(
        purpose=AccessToken.Purpose.BOOKING_VIEW,
        token_hash=_hash(raw),
        booking=booking,
        expires_at=timezone.now() + timedelta(days=days),
    )
    return raw


def issue_checkin_token(ticket, days=30):
    raw = secrets.token_urlsafe(32)
    AccessToken.objects.create(
        purpose=AccessToken.Purpose.CHECKIN,
        token_hash=_hash(raw),
        ticket=ticket,
        booking=ticket.booking,
        expires_at=timezone.now() + timedelta(days=days),
    )
    return raw


def resolve_token(raw, purpose):
    if not raw:
        return None
    token = AccessToken.objects.filter(token_hash=_hash(raw), purpose=purpose, revoked_at__isnull=True).select_related("booking__event", "ticket").first()
    if token is None or token.expires_at <= timezone.now():
        return None
    return token


def revoke_booking_tokens(booking):
    booking.tokens.filter(revoked_at__isnull=True, purpose=AccessToken.Purpose.BOOKING_VIEW).update(revoked_at=timezone.now())


def revoke_ticket_tokens(ticket):
    ticket.tokens.filter(revoked_at__isnull=True).update(revoked_at=timezone.now())
