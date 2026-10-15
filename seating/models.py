import uuid

from django.conf import settings
from django.db import models


class Hold(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event = models.ForeignKey("events.Event", on_delete=models.PROTECT, related_name="holds")
    booking = models.ForeignKey("guests.Booking", null=True, blank=True, on_delete=models.PROTECT, related_name="holds")
    table = models.ForeignKey("layouts.EventTable", null=True, blank=True, on_delete=models.PROTECT, related_name="holds")
    whole_table = models.BooleanField(default=False)
    purpose = models.CharField(max_length=120)
    reason = models.TextField(blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    released_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["event", "expires_at"])]


class SeatOccupancy(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    seat = models.OneToOneField("layouts.Seat", on_delete=models.PROTECT, related_name="occupancy")
    ticket = models.OneToOneField(
        "guests.Ticket", null=True, blank=True, on_delete=models.PROTECT, related_name="occupancy"
    )
    hold = models.ForeignKey(Hold, null=True, blank=True, on_delete=models.PROTECT, related_name="occupancies")
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="assignments"
    )
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(ticket__isnull=False, hold__isnull=True)
                    | models.Q(ticket__isnull=True, hold__isnull=False)
                ),
                name="occupancy_xor",
            ),
        ]
        indexes = [models.Index(fields=["hold"])]
