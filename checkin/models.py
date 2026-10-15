import uuid

from django.conf import settings
from django.db import models


class CheckIn(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ticket = models.OneToOneField("guests.Ticket", on_delete=models.PROTECT, related_name="checkin")
    checked_in_at = models.DateTimeField()
    checked_in_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="checkins"
    )
    device_ref = models.CharField(max_length=80, blank=True)
    undone_at = models.DateTimeField(null=True, blank=True)
    undone_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="undone_checkins"
    )
    undo_reason = models.TextField(blank=True)

    class Meta:
        indexes = [models.Index(fields=["checked_in_at"])]

    @property
    def is_current(self):
        return self.undone_at is None
