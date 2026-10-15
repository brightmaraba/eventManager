import uuid

from django.conf import settings
from django.db import models

from core.errors import DomainError


class LayoutPublication(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event = models.ForeignKey("events.Event", on_delete=models.PROTECT, related_name="publications")
    number = models.PositiveIntegerField()
    snapshot = models.JSONField()
    acknowledged_unassigned = models.BooleanField(default=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["event", "number"], name="unique_publication_number"),
        ]
        ordering = ["-number"]

    def save(self, *args, **kwargs):
        if self.pk and LayoutPublication.objects.filter(pk=self.pk).exists():
            raise DomainError("immutable_publication", "Published layouts cannot be changed.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise DomainError("immutable_publication", "Published layouts cannot be deleted.")
