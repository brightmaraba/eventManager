import uuid

from django.db import models


class Booking(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event = models.ForeignKey("events.Event", on_delete=models.PROTECT, related_name="bookings")
    normalized_email = models.EmailField()
    original_email = models.EmailField()
    party_name = models.CharField(max_length=200, blank=True)
    booking_reference = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)
    accessibility_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["event", "normalized_email"], name="unique_booking_email"),
        ]
        indexes = [models.Index(fields=["event", "normalized_email"])]

    def __str__(self):
        return self.party_name or self.original_email


class Ticket(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        CANCELLED = "cancelled", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    booking = models.ForeignKey(Booking, on_delete=models.PROTECT, related_name="tickets")
    sequence = models.PositiveIntegerField()
    public_code = models.CharField(max_length=40, blank=True)
    display_name = models.CharField(max_length=200, blank=True)
    display_name_custom = models.BooleanField(default=False)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["booking", "sequence"], name="unique_ticket_sequence"),
            models.UniqueConstraint(
                fields=["public_code"],
                condition=models.Q(public_code__gt=""),
                name="unique_public_code",
            ),
        ]
        ordering = ["sequence"]

    def __str__(self):
        return self.public_code or self.display_name or f"Guest {self.sequence}"


class ImportBatch(models.Model):
    class State(models.TextChoices):
        PREVIEW = "preview", "Preview"
        COMMITTED = "committed", "Committed"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event = models.ForeignKey("events.Event", on_delete=models.PROTECT, related_name="imports")
    uploaded_by = models.ForeignKey("accounts.User", null=True, on_delete=models.PROTECT)
    source = models.FileField(upload_to="imports/%Y/%m/", blank=True)
    digest = models.CharField(max_length=64)
    mode = models.JSONField(default=dict)
    roster_revision = models.PositiveIntegerField(default=0)
    state = models.CharField(max_length=16, choices=State.choices, default=State.PREVIEW)
    summary = models.JSONField(default=dict, blank=True)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="children")
    created_at = models.DateTimeField(auto_now_add=True)
    committed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["event", "digest"])]
        ordering = ["-created_at"]


class ImportRow(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch = models.ForeignKey(ImportBatch, on_delete=models.CASCADE, related_name="rows")
    line_number = models.PositiveIntegerField()
    email = models.CharField(max_length=254, blank=True)
    ticket_count = models.IntegerField(null=True, blank=True)
    booking_reference = models.CharField(max_length=120, blank=True)
    party_name = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)
    errors = models.JSONField(default=list, blank=True)
    action = models.CharField(max_length=32, blank=True)
    selected = models.BooleanField(default=True)

    class Meta:
        ordering = ["line_number"]


class AccessToken(models.Model):
    class Purpose(models.TextChoices):
        BOOKING_VIEW = "booking_view", "Booking view"
        CHECKIN = "checkin", "Check-in"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    purpose = models.CharField(max_length=32, choices=Purpose.choices)
    token_hash = models.CharField(max_length=64, unique=True)
    booking = models.ForeignKey(Booking, null=True, blank=True, on_delete=models.CASCADE, related_name="tokens")
    ticket = models.ForeignKey(Ticket, null=True, blank=True, on_delete=models.CASCADE, related_name="tokens")
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["purpose", "expires_at"])]
