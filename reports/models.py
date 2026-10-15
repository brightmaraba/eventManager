import uuid

from django.conf import settings
from django.db import models


class ExportJob(models.Model):
    class State(models.TextChoices):
        PENDING = "pending", "Pending"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"
        DENIED = "denied", "Denied"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event = models.ForeignKey("events.Event", on_delete=models.PROTECT, related_name="exports")
    requester = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="exports")
    kind = models.CharField(max_length=40)
    file_format = models.CharField(max_length=8)
    public_variant = models.BooleanField(default=True)
    publication_id = models.UUIDField(null=True, blank=True)
    snapshot_label = models.CharField(max_length=80, blank=True)
    state = models.CharField(max_length=16, choices=State.choices, default=State.PENDING)
    artifact = models.FileField(upload_to="exports/%Y/%m/", blank=True)
    paper = models.CharField(max_length=8, default="a4")
    orientation = models.CharField(max_length=16, default="landscape")
    fit_mode = models.CharField(max_length=16, default="fit")
    error = models.CharField(max_length=240, blank=True)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["event", "state"])]
