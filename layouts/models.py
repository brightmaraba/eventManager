import uuid

from django.db import models


class Room(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event = models.ForeignKey("events.Event", on_delete=models.PROTECT, related_name="rooms")
    name = models.CharField(max_length=200, default="Main room")
    width_m = models.DecimalField(max_digits=8, decimal_places=3)
    height_m = models.DecimalField(max_digits=8, decimal_places=3)
    scale_px_per_m = models.DecimalField(max_digits=8, decimal_places=3, default=40)
    background = models.FileField(upload_to="room-backgrounds/%Y/%m/", blank=True)
    origin_x = models.DecimalField(max_digits=8, decimal_places=3, default=0)
    origin_y = models.DecimalField(max_digits=8, decimal_places=3, default=0)
    max_occupancy = models.PositiveIntegerField(null=True, blank=True)
    clearance_m = models.DecimalField(max_digits=6, decimal_places=3, default="0.15")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class RoomObstacle(models.Model):
    class Kind(models.TextChoices):
        OBSTACLE = "obstacle", "Obstacle"
        EXIT = "exit", "Exit"
        AISLE = "aisle", "Aisle"
        ACCESSIBILITY = "accessibility", "Accessibility zone"

    class Policy(models.TextChoices):
        WARN = "warn", "Warn"
        BLOCK = "block", "Block"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="obstacles")
    name = models.CharField(max_length=120, blank=True)
    kind = models.CharField(max_length=32, choices=Kind.choices, default=Kind.OBSTACLE)
    clearance_policy = models.CharField(max_length=16, choices=Policy.choices, default=Policy.WARN)
    polygon = models.JSONField(default=list)


class EventTable(models.Model):
    class Shape(models.TextChoices):
        ROUND = "round", "Round"
        RECTANGLE = "rectangle", "Rectangle"
        CUSTOM = "custom", "Custom"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event = models.ForeignKey("events.Event", on_delete=models.PROTECT, related_name="tables")
    room = models.ForeignKey(Room, on_delete=models.PROTECT, related_name="tables")
    label = models.CharField(max_length=40)
    shape = models.CharField(max_length=20, choices=Shape.choices, default=Shape.ROUND)
    width_m = models.DecimalField(max_digits=7, decimal_places=3)
    height_m = models.DecimalField(max_digits=7, decimal_places=3)
    center_x = models.DecimalField(max_digits=8, decimal_places=3)
    center_y = models.DecimalField(max_digits=8, decimal_places=3)
    rotation = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    polygon = models.JSONField(default=list, blank=True)
    category = models.CharField(max_length=80, blank=True)
    notes = models.TextField(blank=True)
    retired_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["event", "label"],
                condition=models.Q(retired_at__isnull=True),
                name="unique_active_table_label",
            ),
        ]
        indexes = [models.Index(fields=["event", "retired_at"])]

    def __str__(self):
        return self.label


class Seat(models.Model):
    class Availability(models.TextChoices):
        ACTIVE = "active", "Active"
        BLOCKED = "blocked", "Blocked"
        RETIRED = "retired", "Retired"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    table = models.ForeignKey(EventTable, on_delete=models.PROTECT, related_name="seats")
    label = models.CharField(max_length=40)
    rel_x = models.DecimalField(max_digits=7, decimal_places=3)
    rel_y = models.DecimalField(max_digits=7, decimal_places=3)
    orientation = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    features = models.JSONField(default=list, blank=True)
    availability = models.CharField(max_length=16, choices=Availability.choices, default=Availability.ACTIVE)
    retired_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["table", "label"],
                condition=models.Q(retired_at__isnull=True),
                name="unique_active_seat_label",
            ),
        ]
        indexes = [models.Index(fields=["table", "availability"])]

    def __str__(self):
        return f"{self.table.label}-{self.label}"


from layouts.publication import LayoutPublication  # noqa: E402,F401
