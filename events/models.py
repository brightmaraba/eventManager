import uuid

from django.conf import settings
from django.db import models


class Event(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"
        COMPLETED = "completed", "Completed"
        ARCHIVED = "archived", "Archived"
        CANCELLED = "cancelled", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey("accounts.Organization", on_delete=models.PROTECT, related_name="events")
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=80)
    description = models.TextField(blank=True)
    venue_name = models.CharField(max_length=200)
    address_line1 = models.CharField(max_length=200)
    address_line2 = models.CharField(max_length=200, blank=True)
    locality = models.CharField(max_length=120)
    region = models.CharField(max_length=120, blank=True)
    postal_code = models.CharField(max_length=32)
    country = models.CharField(max_length=80)
    contact_name = models.CharField(max_length=200, blank=True)
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=40, blank=True)
    logo = models.FileField(upload_to="logos/%Y/%m/", blank=True)
    room_plan = models.FileField(upload_to="room-plans/%Y/%m/", blank=True)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    timezone = models.CharField(max_length=64)
    doors_open_at = models.DateTimeField(null=True, blank=True)
    initial_table_count = models.PositiveIntegerField(default=0)
    default_seats_per_table = models.PositiveIntegerField(default=8)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    status_before_archive = models.CharField(max_length=20, blank=True)
    accessibility_notes = models.TextField(blank=True)
    internal_notes = models.TextField(blank=True)
    roster_revision = models.PositiveIntegerField(default=0)
    layout_revision = models.PositiveIntegerField(default=0)
    active_publication_id = models.UUIDField(null=True, blank=True)
    republish_required = models.BooleanField(default=False)
    personal_data_purged_at = models.DateTimeField(null=True, blank=True)
    retention_date = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="events_created")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "slug"], name="unique_event_slug"),
        ]
        indexes = [
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["starts_at"]),
        ]
        ordering = ["-starts_at"]

    def __str__(self):
        return self.name

    @property
    def active_publication(self):
        if not self.active_publication_id:
            return None
        return self.publications.filter(pk=self.active_publication_id).first()
