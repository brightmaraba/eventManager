import uuid

from django.conf import settings
from django.db import models


class Campaign(models.Model):
    class Kind(models.TextChoices):
        INVITATION = "invitation", "Invitation"
        SEATING = "seating", "Seating confirmation"
        CHANGES = "changes", "Changed seating"
        REMINDER = "reminder", "Reminder"
        CANCELLATION = "cancellation", "Cancellation"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SCHEDULED = "scheduled", "Scheduled"
        SENDING = "sending", "Sending"
        SENT = "sent", "Sent"
        CANCELLED = "cancelled", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event = models.ForeignKey("events.Event", on_delete=models.PROTECT, related_name="campaigns")
    kind = models.CharField(max_length=32, choices=Kind.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    subject = models.CharField(max_length=200)
    html_body = models.TextField(blank=True)
    text_body = models.TextField(blank=True)
    audience_filter = models.JSONField(default=dict)
    scheduled_at = models.DateTimeField(null=True, blank=True)
    is_test = models.BooleanField(default=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class CampaignAudience(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    campaign = models.OneToOneField(Campaign, on_delete=models.PROTECT, related_name="audience")
    publication = models.ForeignKey(
        "layouts.LayoutPublication", null=True, blank=True, on_delete=models.PROTECT, related_name="audiences"
    )
    booking_ids = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)


class EmailDelivery(models.Model):
    class State(models.TextChoices):
        PENDING = "pending", "Pending"
        CLAIMED = "claimed", "Claimed"
        SUBMITTED = "submitted", "Submitted"
        DELIVERED = "delivered", "Delivered"
        BOUNCED = "bounced", "Bounced"
        FAILED = "failed", "Failed"
        SUPPRESSED = "suppressed", "Suppressed"
        AMBIGUOUS = "ambiguous", "Ambiguous"
        CANCELLED = "cancelled", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    audience = models.ForeignKey(CampaignAudience, on_delete=models.PROTECT, related_name="deliveries")
    booking = models.ForeignKey("guests.Booking", on_delete=models.PROTECT, related_name="deliveries")
    state = models.CharField(max_length=16, choices=State.choices, default=State.PENDING)
    recipient_email = models.EmailField(blank=True)
    subject = models.CharField(max_length=200, blank=True)
    html_body = models.TextField(blank=True)
    text_body = models.TextField(blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    claimed_at = models.DateTimeField(null=True, blank=True)
    smtp_started = models.BooleanField(default=False)
    provider_message_id = models.CharField(max_length=120, blank=True)
    last_error = models.CharField(max_length=240, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["audience", "booking"], name="unique_logical_delivery"),
        ]
        indexes = [
            models.Index(fields=["state", "next_attempt_at"]),
        ]


class DeliveryAttempt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    delivery = models.ForeignKey(EmailDelivery, on_delete=models.PROTECT, related_name="attempt_history")
    result = models.CharField(max_length=32)
    detail = models.CharField(max_length=240, blank=True)
    provider_message_id = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class ProviderEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider_event_id = models.CharField(max_length=120, unique=True)
    delivery = models.ForeignKey(EmailDelivery, null=True, blank=True, on_delete=models.PROTECT, related_name="provider_events")
    event_type = models.CharField(max_length=64)
    payload = models.JSONField(default=dict)
    received_at = models.DateTimeField(auto_now_add=True)


class Suppression(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey("accounts.Organization", on_delete=models.CASCADE, related_name="suppressions")
    normalized_email = models.EmailField()
    reason = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "normalized_email"], name="unique_suppression"),
        ]
