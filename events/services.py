from datetime import datetime, timezone as datetime_timezone
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from audit.services import record
from core.errors import Conflict, DomainError
from core.locking import lock_event


def bump(event, *, roster=False, layout=False):
    fields = ["updated_at"]
    if roster:
        event.roster_revision += 1
        fields.append("roster_revision")
    if layout:
        event.layout_revision += 1
        fields.append("layout_revision")
    if event.active_publication_id and (roster or layout):
        event.republish_required = True
        fields.append("republish_required")
    event.save(update_fields=fields)


def unique_slug(model, value, scope=None, scope_field=None):
    base = (slugify(value) or "item")[:70]
    slug = base
    number = 2
    while True:
        query = model.objects.filter(slug=slug)
        if scope is not None:
            query = query.filter(**{scope_field: scope})
        if not query.exists():
            return slug
        slug = f"{base}-{number}"[:80]
        number += 1


def parse_local_datetime(value, timezone_name):
    if isinstance(value, datetime):
        naive = value.replace(tzinfo=None) if value.tzinfo else value
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1]
        naive = datetime.fromisoformat(text)
        if naive.tzinfo is not None:
            naive = naive.astimezone(ZoneInfo(timezone_name)).replace(tzinfo=None)
    if timezone_name not in available_timezones():
        raise DomainError("invalid_timezone", "Choose a valid IANA timezone.", field_errors={"timezone": "Choose a valid IANA timezone."})
    zone = ZoneInfo(timezone_name)
    aware = naive.replace(tzinfo=zone)
    utc_value = aware.astimezone(datetime_timezone.utc)
    roundtrip = utc_value.astimezone(zone).replace(tzinfo=None)
    if roundtrip != naive:
        raise DomainError(
            "invalid_datetime",
            "That local time does not exist in the event timezone.",
            field_errors={"starts_at": "That local time does not exist in this timezone."},
        )
    return utc_value


def available_timezones():
    from zoneinfo import available_timezones as zones

    return zones()


def validate_schedule(data):
    timezone_name = data["timezone"]
    if timezone_name not in available_timezones():
        raise DomainError("invalid_timezone", "Choose a valid IANA timezone.", field_errors={"timezone": "Choose a valid IANA timezone."})
    starts = parse_local_datetime(data["starts_at"], timezone_name)
    ends = parse_local_datetime(data["ends_at"], timezone_name)
    if ends <= starts:
        raise DomainError("invalid_schedule", "The end must be after the start.", field_errors={"ends_at": "End must be after the start."})
    doors = data.get("doors_open_at")
    doors_utc = None
    if doors:
        doors_utc = parse_local_datetime(doors, timezone_name)
        if doors_utc > starts:
            raise DomainError(
                "invalid_schedule",
                "Doors open cannot be later than the start.",
                field_errors={"doors_open_at": "Doors open cannot be later than the start."},
            )
    table_count = int(data.get("initial_table_count") or 0)
    default_seats = int(data.get("default_seats_per_table") or 8)
    if table_count < 0 or default_seats < 1:
        raise DomainError("invalid_capacity_input", "Table count cannot be negative, and each new table needs at least one seat.")
    required = ["name", "venue_name", "address_line1", "locality", "postal_code", "country"]
    missing = {field: "This field is required." for field in required if not str(data.get(field, "")).strip()}
    if missing:
        raise DomainError("invalid_event", "Enter the event name and venue address.", field_errors=missing)
    return starts, ends, doors_utc, table_count, default_seats


def clean_upload(uploaded, *, label):
    from io import BytesIO

    from PIL import Image, UnidentifiedImageError

    raw = uploaded.read()
    if len(raw) > 2 * 1024 * 1024:
        raise DomainError("image_too_large", f"{label} must be 2 MB or smaller.")
    prefix = raw[:300].lower().lstrip()
    if prefix.startswith(b"<") or b"<svg" in prefix or b"<html" in prefix:
        raise DomainError("image_rejected", "SVG and HTML uploads are not allowed.")
    try:
        probe = Image.open(BytesIO(raw))
        probe.verify()
        image = Image.open(BytesIO(raw))
        image.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise DomainError("image_rejected", "Upload a PNG, JPEG, or WebP image.") from exc
    if image.format not in {"PNG", "JPEG", "WEBP"}:
        raise DomainError("image_rejected", "Upload a PNG, JPEG, or WebP image.")
    if image.width > 4096 or image.height > 4096 or image.width < 1 or image.height < 1:
        raise DomainError("image_rejected", "Images must be between 1 and 4096 pixels on each side.")
    if image.mode not in {"RGB", "RGBA"}:
        image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
    output = BytesIO()
    image.save(output, format="PNG")
    output.seek(0)
    return output


@transaction.atomic
def create_event(*, actor, organization, data, request_id):
    from events.models import Event

    starts, ends, doors, table_count, default_seats = validate_schedule(data)
    event = Event.objects.create(
        organization=organization,
        name=data["name"].strip(),
        slug=unique_slug(Event, data["name"], organization, "organization"),
        description=data.get("description", ""),
        venue_name=data["venue_name"].strip(),
        address_line1=data["address_line1"].strip(),
        address_line2=data.get("address_line2", ""),
        locality=data["locality"].strip(),
        region=data.get("region", ""),
        postal_code=data["postal_code"].strip(),
        country=data["country"].strip(),
        contact_name=data.get("contact_name", ""),
        contact_email=data.get("contact_email", ""),
        contact_phone=data.get("contact_phone", ""),
        starts_at=starts,
        ends_at=ends,
        timezone=data["timezone"],
        doors_open_at=doors,
        initial_table_count=table_count,
        default_seats_per_table=default_seats,
        accessibility_notes=data.get("accessibility_notes", ""),
        internal_notes=data.get("internal_notes", ""),
        created_by=actor,
    )
    from layouts.services import ensure_room, generate_tables

    room = ensure_room(event)
    if table_count:
        generate_tables(event, room, table_count, default_seats, actor, request_id)
    record(
        actor=actor,
        organization=organization,
        event=event,
        operation="event_created",
        object_type="event",
        object_id=event.id,
        after={"name": event.name, "status": event.status},
        request_id=request_id,
    )
    return event


@transaction.atomic
def update_event(*, actor, event, data, request_id):
    event = lock_event(event.id)
    starts, ends, doors, table_count, default_seats = validate_schedule({**event_form_data(event), **data})
    for field in [
        "name", "description", "venue_name", "address_line1", "address_line2", "locality", "region",
        "postal_code", "country", "contact_name", "contact_email", "contact_phone", "accessibility_notes", "internal_notes",
    ]:
        if field in data:
            setattr(event, field, data[field])
    event.starts_at = starts
    event.ends_at = ends
    event.doors_open_at = doors
    event.timezone = data.get("timezone", event.timezone)
    event.initial_table_count = table_count
    event.default_seats_per_table = default_seats
    event.save()
    record(actor=actor, organization=event.organization, event=event, operation="event_updated", object_type="event", object_id=event.id, request_id=request_id, after={"name": event.name})
    return event


def event_form_data(event):
    zone = ZoneInfo(event.timezone)

    def local(value):
        if not value:
            return ""
        return value.astimezone(zone).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M")

    return {
        "name": event.name,
        "description": event.description,
        "venue_name": event.venue_name,
        "address_line1": event.address_line1,
        "address_line2": event.address_line2,
        "locality": event.locality,
        "region": event.region,
        "postal_code": event.postal_code,
        "country": event.country,
        "contact_name": event.contact_name,
        "contact_email": event.contact_email,
        "contact_phone": event.contact_phone,
        "starts_at": local(event.starts_at),
        "ends_at": local(event.ends_at),
        "doors_open_at": local(event.doors_open_at),
        "timezone": event.timezone,
        "initial_table_count": event.initial_table_count,
        "default_seats_per_table": event.default_seats_per_table,
        "accessibility_notes": event.accessibility_notes,
        "internal_notes": event.internal_notes,
    }


@transaction.atomic
def save_image(*, actor, event, uploaded, field, request_id):
    from django.core.files.base import ContentFile

    event = lock_event(event.id)
    cleaned = clean_upload(uploaded, label="Image")
    filename = f"{event.id}.png"
    getattr(event, field).save(filename, ContentFile(cleaned.read()), save=True)
    record(actor=actor, organization=event.organization, event=event, operation="image_updated", object_type="event", object_id=event.id, request_id=request_id, after={"field": field})
    return event


@transaction.atomic
def change_status(*, actor, event, action, reason, request_id):
    event = lock_event(event.id)
    current = event.status
    if action == "archive":
        if current == event.Status.ARCHIVED:
            return event
        event.status_before_archive = current
        event.status = event.Status.ARCHIVED
    elif action == "unarchive":
        if current != event.Status.ARCHIVED:
            raise Conflict("invalid_transition", "Only an archived event can be reopened from the archive.")
        event.status = event.status_before_archive or event.Status.COMPLETED
    elif action == "complete":
        if current != event.Status.PUBLISHED:
            raise Conflict("invalid_transition", "Only a published event can be marked completed.")
        event.status = event.Status.COMPLETED
        from datetime import timedelta

        event.retention_date = timezone.now().date() + timedelta(days=event.organization.retention_event_days)
    elif action == "reopen":
        if current != event.Status.COMPLETED:
            raise Conflict("invalid_transition", "Only a completed event can be reopened.")
        if not reason:
            raise DomainError("reason_required", "Reopening a completed event requires a reason.")
        event.status = event.Status.PUBLISHED
    elif action == "cancel":
        if current not in {event.Status.DRAFT, event.Status.PUBLISHED}:
            raise Conflict("invalid_transition", "This event cannot be cancelled.")
        if not reason:
            raise DomainError("reason_required", "Cancellation requires a reason.")
        event.status = event.Status.CANCELLED
        from communications.services import cancel_event_campaigns

        cancel_event_campaigns(event=event, actor=actor, request_id=request_id, reason=reason)
    else:
        raise DomainError("invalid_action", "Unknown event action.")
    event.save()
    record(
        actor=actor,
        organization=event.organization,
        event=event,
        operation=f"event_{action}",
        object_type="event",
        object_id=event.id,
        reason=reason,
        request_id=request_id,
        before={"status": current},
        after={"status": event.status},
    )
    return event


@transaction.atomic
def duplicate_event(*, actor, event, name, request_id):
    from events.models import Event
    from layouts.models import EventTable, Room, RoomObstacle, Seat

    source = lock_event(event.id)
    copy = Event.objects.create(
        organization=source.organization,
        name=name.strip() or f"{source.name} copy",
        slug=unique_slug(Event, name or source.name, source.organization, "organization"),
        description=source.description,
        venue_name=source.venue_name,
        address_line1=source.address_line1,
        address_line2=source.address_line2,
        locality=source.locality,
        region=source.region,
        postal_code=source.postal_code,
        country=source.country,
        contact_name=source.contact_name,
        contact_email=source.contact_email,
        contact_phone=source.contact_phone,
        starts_at=source.starts_at,
        ends_at=source.ends_at,
        timezone=source.timezone,
        doors_open_at=source.doors_open_at,
        initial_table_count=source.initial_table_count,
        default_seats_per_table=source.default_seats_per_table,
        accessibility_notes=source.accessibility_notes,
        internal_notes=source.internal_notes,
        created_by=actor,
    )
    for room in source.rooms.all():
        new_room = Room.objects.create(
            event=copy, name=room.name, width_m=room.width_m, height_m=room.height_m,
            scale_px_per_m=room.scale_px_per_m, origin_x=room.origin_x, origin_y=room.origin_y,
            max_occupancy=room.max_occupancy, clearance_m=room.clearance_m,
        )
        for obstacle in room.obstacles.all():
            RoomObstacle.objects.create(
                room=new_room, name=obstacle.name, kind=obstacle.kind,
                clearance_policy=obstacle.clearance_policy, polygon=obstacle.polygon,
            )
        for table in room.tables.filter(retired_at__isnull=True):
            new_table = EventTable.objects.create(
                event=copy, room=new_room, label=table.label, shape=table.shape, width_m=table.width_m,
                height_m=table.height_m, center_x=table.center_x, center_y=table.center_y, rotation=table.rotation,
                polygon=table.polygon, category=table.category, notes=table.notes,
            )
            for seat in table.seats.filter(retired_at__isnull=True):
                Seat.objects.create(
                    table=new_table, label=seat.label, rel_x=seat.rel_x, rel_y=seat.rel_y,
                    orientation=seat.orientation, features=seat.features, availability=seat.availability,
                )
    record(actor=actor, organization=copy.organization, event=copy, operation="event_duplicated", object_type="event", object_id=copy.id, request_id=request_id, after={"source": str(source.id)})
    return copy


def event_metrics(event):
    from checkin.models import CheckIn
    from guests.models import Ticket
    from layouts.models import Seat
    from seating.models import SeatOccupancy

    seats = Seat.objects.filter(table__event=event, table__retired_at__isnull=True, retired_at__isnull=True)
    active = seats.filter(availability=Seat.Availability.ACTIVE)
    now = timezone.now()
    occupancies = SeatOccupancy.objects.filter(seat__in=active)
    held = occupancies.filter(hold__isnull=False, hold__released_at__isnull=True).exclude(hold__expires_at__lte=now).count()
    assigned = occupancies.filter(ticket__isnull=False, ticket__status=Ticket.Status.ACTIVE).count()
    tickets = Ticket.objects.filter(booking__event=event, status=Ticket.Status.ACTIVE).count()
    checked_in = CheckIn.objects.filter(ticket__booking__event=event, ticket__status=Ticket.Status.ACTIVE, undone_at__isnull=True).count()
    return {
        "tickets": tickets,
        "capacity": active.count(),
        "blocked": seats.filter(availability=Seat.Availability.BLOCKED).count(),
        "held": held,
        "assigned": assigned,
        "unassigned": max(tickets - assigned, 0),
        "checked_in": checked_in,
    }


@transaction.atomic
def purge_personal_data(*, actor, event, reason, request_id):
    from guests.models import Booking

    if not reason:
        raise DomainError("reason_required", "A reason is required before personal data is removed.")
    event = lock_event(event.id)
    if event.status not in {event.Status.COMPLETED, event.Status.ARCHIVED, event.Status.CANCELLED}:
        raise Conflict("event_live", "Personal data can be removed only after the event is finished, archived, or cancelled.")
    for booking in event.bookings.all():
        booking.original_email = f"removed-{booking.id}@example.test"
        booking.normalized_email = booking.original_email
        booking.party_name = ""
        booking.notes = ""
        booking.accessibility_notes = ""
        booking.booking_reference = ""
        booking.save()
        booking.tickets.update(display_name="Removed guest", display_name_custom=True)
    event.personal_data_purged_at = timezone.now()
    event.contact_email = ""
    event.contact_name = ""
    event.contact_phone = ""
    event.internal_notes = ""
    event.save()
    record(actor=actor, organization=event.organization, event=event, operation="personal_data_purged", object_type="event", object_id=event.id, reason=reason, request_id=request_id)
    return event
