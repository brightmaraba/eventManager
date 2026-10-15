from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from accounts.permissions import can_communicate
from audit.services import record
from communications.models import Campaign, CampaignAudience, DeliveryAttempt, EmailDelivery
from communications.provider import AmbiguousSMTP, PermanentSMTP, TransientSMTP, deliver
from communications.rendering import render_message
from core.errors import Conflict, DomainError, NotFound
from core.locking import lock_event
from guests.models import Booking
from guests.services import normalize_email
from layouts.publication_service import diff_publications


def _bookings_for(event, audience_filter, publication):
    del publication
    kind = (audience_filter or {}).get("kind", "all")
    rows = list(Booking.objects.filter(event=event).order_by("original_email"))
    if kind == "selected":
        wanted = set(str(value) for value in audience_filter.get("booking_ids", []))
        rows = [booking for booking in rows if str(booking.id) in wanted]
    elif kind == "assigned":
        rows = [booking for booking in rows if booking.tickets.filter(status="active", occupancy__isnull=False).exists()]
    elif kind == "unassigned":
        rows = [booking for booking in rows if booking.tickets.filter(status="active", occupancy__isnull=True).exists()]
    elif kind == "changed":
        previous = event.publications.filter(pk=audience_filter.get("since_publication_id")).first()
        current = event.active_publication
        if not previous or not current:
            return []
        wanted = set(diff_publications(previous, current))
        rows = [booking for booking in rows if str(booking.id) in wanted]
    elif kind == "failures":
        rows = [booking for booking in rows if booking.deliveries.filter(state__in=["failed", "bounced"]).exists()]
    return rows


@transaction.atomic
def create_campaign(*, event, actor, kind, subject, audience_filter, request_id):
    if kind not in Campaign.Kind.values:
        raise DomainError("invalid_campaign", "Choose a known message type.")
    campaign = Campaign.objects.create(
        event=event, kind=kind, subject=subject.strip(), audience_filter=audience_filter or {"kind": "all"}, created_by=actor,
    )
    record(actor=actor, organization=event.organization, event=event, operation="campaign_drafted", object_type="campaign", object_id=campaign.id, request_id=request_id)
    return campaign


def preview_campaign(campaign, booking=None):
    booking = booking or campaign.event.bookings.order_by("created_at").first()
    if booking is None:
        raise DomainError("no_recipients", "Import a booking before previewing mail.")
    subject, html, text = render_message(campaign, booking, campaign.event.active_publication, issue_link=False)
    return {"subject": subject, "html": html, "text": text, "recipient": booking.original_email}


def _materialize(campaign, bookings, actor):
    publication = campaign.event.active_publication
    audience = CampaignAudience.objects.create(
        campaign=campaign,
        publication=publication,
        booking_ids=[str(booking.id) for booking in bookings],
    )
    deliveries = []
    for booking in bookings:
        subject, html, text = render_message(campaign, booking, publication, issue_link=True)
        delivery = EmailDelivery.objects.create(
            audience=audience,
            booking=booking,
            recipient_email=booking.original_email,
            subject=subject,
            html_body=html,
            text_body=text,
        )
        deliveries.append(delivery)
    return audience, deliveries


@transaction.atomic
def queue_campaign(*, campaign, actor, request_id, when=None, test_recipient=""):
    event = lock_event(campaign.event_id)
    campaign = Campaign.objects.select_for_update().get(pk=campaign.id)
    if campaign.status not in {Campaign.Status.DRAFT, Campaign.Status.SCHEDULED}:
        raise Conflict("campaign_closed", "This campaign can no longer be sent.")
    if test_recipient:
        booking = event.bookings.order_by("created_at").first()
        if booking is None:
            raise DomainError("no_recipients", "Import a booking before sending a test.")
        test = Campaign.objects.create(
            event=event, kind=campaign.kind, subject=campaign.subject, audience_filter={"kind": "test"},
            created_by=actor, is_test=True, status=Campaign.Status.SENDING,
        )
        audience = CampaignAudience.objects.create(campaign=test, publication=event.active_publication, booking_ids=[str(booking.id)])
        subject, html, text = render_message(campaign, booking, event.active_publication, issue_link=True)
        EmailDelivery.objects.create(
            audience=audience, booking=booking, recipient_email=test_recipient, subject=subject, html_body=html, text_body=text,
        )
        record(actor=actor, organization=event.organization, event=event, operation="campaign_test_queued", object_type="campaign", object_id=test.id, request_id=request_id)
        return test
    bookings = _bookings_for(event, campaign.audience_filter, event.active_publication)
    if not bookings:
        raise DomainError("no_recipients", "That audience has no bookings.")
    if when and when > timezone.now():
        campaign.scheduled_at = when
        campaign.status = Campaign.Status.SCHEDULED
        campaign.save(update_fields=["scheduled_at", "status"])
        record(actor=actor, organization=event.organization, event=event, operation="campaign_scheduled", object_type="campaign", object_id=campaign.id, request_id=request_id)
        return campaign
    _materialize(campaign, bookings, actor)
    campaign.status = Campaign.Status.SENDING
    campaign.save(update_fields=["status"])
    record(actor=actor, organization=event.organization, event=event, operation="campaign_queued", object_type="campaign", object_id=campaign.id, request_id=request_id, after={"recipients": len(bookings)})
    return campaign


@transaction.atomic
def cancel_campaign(*, campaign, actor, request_id, reason):
    event = lock_event(campaign.event_id)
    campaign = Campaign.objects.select_for_update().get(pk=campaign.id)
    campaign.status = Campaign.Status.CANCELLED
    campaign.save(update_fields=["status"])
    if hasattr(campaign, "audience"):
        campaign.audience.deliveries.filter(state=EmailDelivery.State.PENDING).update(state=EmailDelivery.State.CANCELLED, last_error=reason[:240])
    record(actor=actor, organization=event.organization, event=event, operation="campaign_cancelled", object_type="campaign", object_id=campaign.id, reason=reason, request_id=request_id)
    return campaign


def cancel_event_campaigns(*, event, actor, request_id, reason):
    for campaign in event.campaigns.filter(status__in=[Campaign.Status.DRAFT, Campaign.Status.SCHEDULED, Campaign.Status.SENDING]):
        cancel_campaign(campaign=campaign, actor=actor, request_id=request_id, reason=reason)


def dispatch_due_campaigns():
    due = Campaign.objects.filter(status=Campaign.Status.SCHEDULED, scheduled_at__lte=timezone.now())
    for campaign in due:
        if hasattr(campaign, "audience"):
            continue
        bookings = _bookings_for(campaign.event, campaign.audience_filter, campaign.event.active_publication)
        if campaign.event.status == "cancelled":
            campaign.status = Campaign.Status.CANCELLED
            campaign.save(update_fields=["status"])
            continue
        with transaction.atomic():
            locked = Campaign.objects.select_for_update().get(pk=campaign.id)
            if locked.status != Campaign.Status.SCHEDULED:
                continue
            if bookings:
                _materialize(locked, bookings, locked.created_by)
            locked.status = Campaign.Status.SENDING
            locked.save(update_fields=["status"])


def _rate_ok(organization_id):
    key = f"mail-rate:{organization_id}:{int(timezone.now().timestamp()) // 60}"
    try:
        if cache.add(key, 0, 90):
            pass
        count = cache.incr(key)
    except Exception:
        return True
    return count <= settings.EMAIL_RATE_PER_MINUTE


def dispatch_pending(limit=100):
    dispatch_due_campaigns()
    now = timezone.now()
    identifiers = list(
        EmailDelivery.objects.filter(state=EmailDelivery.State.PENDING)
        .filter(Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now))
        .order_by("created_at")
        .values_list("id", flat=True)[:limit]
    )
    for delivery_id in identifiers:
        _send_one(delivery_id)


def _send_one(delivery_id):
    from communications.models import Suppression

    with transaction.atomic():
        try:
            delivery = EmailDelivery.objects.select_for_update(of=("self",)).select_related(
                "booking__event__organization", "audience__campaign__created_by", "audience__publication"
            ).get(pk=delivery_id)
        except EmailDelivery.DoesNotExist:
            return
        if delivery.state != EmailDelivery.State.PENDING:
            return
        event = delivery.booking.event
        campaign = delivery.audience.campaign
        if event.status == "cancelled" or campaign.status == Campaign.Status.CANCELLED:
            delivery.state = EmailDelivery.State.CANCELLED
            delivery.last_error = "event_or_campaign_cancelled"
            delivery.save(update_fields=["state", "last_error", "updated_at"])
            return
        creator = campaign.created_by
        if creator and not can_communicate(creator, event):
            delivery.state = EmailDelivery.State.FAILED
            delivery.last_error = "permission_revoked"
            delivery.save(update_fields=["state", "last_error", "updated_at"])
            return
        if Suppression.objects.filter(organization=event.organization, normalized_email=normalize_email(delivery.recipient_email)).exists():
            delivery.state = EmailDelivery.State.SUPPRESSED
            delivery.save(update_fields=["state", "updated_at"])
            return
        if not _rate_ok(event.organization_id):
            delivery.next_attempt_at = timezone.now() + timedelta(seconds=30)
            delivery.save(update_fields=["next_attempt_at", "updated_at"])
            return
        delivery.state = EmailDelivery.State.CLAIMED
        delivery.claimed_at = timezone.now()
        delivery.smtp_started = False
        delivery.save(update_fields=["state", "claimed_at", "smtp_started", "updated_at"])
    delivery.refresh_from_db()
    delivery.smtp_started = True
    delivery.save(update_fields=["smtp_started", "updated_at"])
    try:
        message_id = deliver(delivery)
    except AmbiguousSMTP as exc:
        delivery.state = EmailDelivery.State.AMBIGUOUS
        delivery.last_error = str(exc)[:240]
        delivery.save(update_fields=["state", "last_error", "updated_at"])
        DeliveryAttempt.objects.create(delivery=delivery, result="ambiguous", detail=delivery.last_error)
        return
    except PermanentSMTP as exc:
        delivery.state = EmailDelivery.State.FAILED
        delivery.attempts += 1
        delivery.last_error = str(exc)[:240]
        delivery.save(update_fields=["state", "attempts", "last_error", "updated_at"])
        DeliveryAttempt.objects.create(delivery=delivery, result="failed", detail=delivery.last_error)
        return
    except TransientSMTP as exc:
        delivery.attempts += 1
        delivery.last_error = str(exc)[:240]
        if delivery.attempts >= 5:
            delivery.state = EmailDelivery.State.FAILED
        else:
            delivery.state = EmailDelivery.State.PENDING
            delivery.smtp_started = False
            delivery.next_attempt_at = timezone.now() + timedelta(seconds=min(300, 2 ** delivery.attempts))
        delivery.save(update_fields=["state", "attempts", "smtp_started", "next_attempt_at", "last_error", "updated_at"])
        DeliveryAttempt.objects.create(delivery=delivery, result=delivery.state, detail=delivery.last_error)
        return
    delivery.state = EmailDelivery.State.SUBMITTED
    delivery.provider_message_id = message_id or ""
    delivery.save(update_fields=["state", "provider_message_id", "updated_at"])
    DeliveryAttempt.objects.create(delivery=delivery, result="submitted", provider_message_id=delivery.provider_message_id)
    campaign = delivery.audience.campaign
    if not campaign.audience.deliveries.exclude(state__in=[EmailDelivery.State.SUBMITTED, EmailDelivery.State.DELIVERED, EmailDelivery.State.FAILED, EmailDelivery.State.BOUNCED, EmailDelivery.State.SUPPRESSED, EmailDelivery.State.CANCELLED, EmailDelivery.State.AMBIGUOUS]).exists():
        if campaign.status == Campaign.Status.SENDING:
            campaign.status = Campaign.Status.SENT
            campaign.save(update_fields=["status"])


def reconcile_abandoned_claims(minutes=10):
    cutoff = timezone.now() - timedelta(minutes=minutes)
    for delivery in EmailDelivery.objects.filter(state=EmailDelivery.State.CLAIMED, claimed_at__lt=cutoff):
        if delivery.smtp_started:
            delivery.state = EmailDelivery.State.AMBIGUOUS
            delivery.last_error = "abandoned_after_smtp_started"
        else:
            delivery.state = EmailDelivery.State.PENDING
            delivery.last_error = "abandoned_before_smtp"
        delivery.save(update_fields=["state", "last_error", "updated_at"])


def get_campaign(event, campaign_id):
    try:
        return event.campaigns.get(pk=campaign_id)
    except Campaign.DoesNotExist as exc:
        raise NotFound() from exc
