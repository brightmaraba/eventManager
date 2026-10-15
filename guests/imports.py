import csv
import hashlib
import json
from io import StringIO

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from audit.services import record
from core.errors import Conflict, DomainError, TooLarge
from core.locking import lock_event
from events.services import bump
from guests.models import Booking, ImportBatch, ImportRow
from guests.services import get_or_create_booking, normalize_email, set_quantity

REQUIRED = {"email", "ticket_count"}
OPTIONAL = {"booking_reference", "party_name", "notes"}
REJECTED = {"attendee_names"}


def escape_formula(value):
    text = "" if value is None else str(value)
    if text[:1] in {"=", "+", "-", "@", "\t", "\r"}:
        return "'" + text
    return text


def _mode(duplicate_policy, quantity_policy, replace_roster, confirm_replace_roster):
    return {
        "duplicate_policy": duplicate_policy or "reject",
        "quantity_policy": quantity_policy or "replace",
        "replace_roster": bool(replace_roster),
        "confirm_replace_roster": bool(confirm_replace_roster),
    }


def _digest(raw, mode):
    payload = raw + b"\n" + json.dumps(mode, sort_keys=True).encode()
    return hashlib.sha256(payload).hexdigest()


def parse_csv(raw):
    if len(raw) > settings.IMPORT_MAX_BYTES:
        raise TooLarge(f"CSV uploads must be {settings.IMPORT_MAX_BYTES // (1024 * 1024)} MB or smaller.")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DomainError("csv_encoding", "Upload a UTF-8 CSV file.") from exc
    reader = csv.DictReader(StringIO(text, newline=""))
    if not reader.fieldnames:
        raise DomainError("csv_header", "The CSV needs a header row with email and ticket_count.")
    fields = [(name or "").strip() for name in reader.fieldnames]
    unknown = [name for name in fields if name and name not in REQUIRED | OPTIONAL]
    if any(name in REJECTED for name in fields):
        raise DomainError(
            "unsupported_column",
            "attendee_names is not accepted in version 1. Edit attendee names after the import.",
        )
    if unknown:
        raise DomainError("unsupported_column", "Unsupported column: " + ", ".join(unknown) + ".")
    missing = REQUIRED - set(fields)
    if missing:
        raise DomainError("csv_header", "The CSV must include email and ticket_count.")
    rows = []
    for index, row in enumerate(reader, start=2):
        if index - 1 > settings.IMPORT_MAX_ROWS:
            raise TooLarge(f"CSV imports are limited to {settings.IMPORT_MAX_ROWS} rows.")
        cleaned = {key.strip(): (value or "").strip() if value else "" for key, value in row.items() if key}
        rows.append((index, cleaned))
    return rows


def _row_errors(data):
    errors = []
    email = data.get("email", "")
    try:
        validate_email(email)
    except ValidationError:
        errors.append("Enter a valid email address.")
    raw_count = data.get("ticket_count", "")
    count = None
    if raw_count == "" or not _positive_int(raw_count):
        errors.append("ticket_count must be a positive whole number.")
    else:
        count = int(raw_count)
        if count > settings.IMPORT_MAX_TICKETS_PER_ROW:
            errors.append(f"ticket_count cannot exceed {settings.IMPORT_MAX_TICKETS_PER_ROW}.")
    return errors, count


def _positive_int(value):
    if value.startswith("+"):
        return False
    return value.isdigit() and int(value) > 0


@transaction.atomic
def preview_import(*, event, actor, raw, filename, request_id, duplicate_policy="reject", quantity_policy="replace", replace_roster=False, confirm_replace_roster=False, force_new=False):
    event = lock_event(event.id)
    mode = _mode(duplicate_policy, quantity_policy, replace_roster, confirm_replace_roster)
    if mode["quantity_policy"] not in {"replace", "additive"} or mode["duplicate_policy"] not in {"reject", "aggregate"}:
        raise DomainError("invalid_mode", "Choose a supported duplicate and quantity mode.")
    if mode["quantity_policy"] == "additive" and mode["duplicate_policy"] != "aggregate" and False:
        pass
    digest = _digest(raw, mode)
    if not force_new:
        previous = ImportBatch.objects.filter(event=event, digest=digest, state=ImportBatch.State.COMMITTED).order_by("-committed_at").first()
        if previous and previous.mode == mode:
            return previous
    parsed = parse_csv(raw)
    grouped = {}
    order = []
    duplicates = set()
    for line_number, data in parsed:
        email = normalize_email(data.get("email", ""))
        if email in grouped and mode["duplicate_policy"] == "reject":
            duplicates.add(email)
        if email not in grouped:
            order.append(email)
            grouped[email] = {"lines": [line_number], "data": data, "counts": []}
        else:
            grouped[email]["lines"].append(line_number)
        grouped[email]["counts"].append(data.get("ticket_count", ""))
    batch = ImportBatch.objects.create(
        event=event, uploaded_by=actor, digest=digest, mode=mode, roster_revision=event.roster_revision, state=ImportBatch.State.PREVIEW,
    )
    batch.source.save(filename or "import.csv", ContentFile(raw), save=True)
    for email in order:
        item = grouped[email]
        data = item["data"]
        errors, count = _row_errors(data)
        if mode["duplicate_policy"] == "reject" and email in duplicates:
            errors.append("This email appears more than once. Reject the file or choose aggregate mode.")
            count = None
        elif mode["duplicate_policy"] == "aggregate":
            total = 0
            bad = False
            for raw_count in item["counts"]:
                if not _positive_int(raw_count):
                    bad = True
                else:
                    total += int(raw_count)
            if bad:
                errors.append("Every duplicate row needs a positive whole ticket_count before counts can be combined.")
                count = None
            else:
                count = total
                errors = [error for error in errors if "ticket_count" not in error]
        action = "error" if errors else "upsert"
        ImportRow.objects.create(
            batch=batch,
            line_number=item["lines"][0],
            email=data.get("email", ""),
            ticket_count=count,
            booking_reference=data.get("booking_reference", ""),
            party_name=data.get("party_name", ""),
            notes=data.get("notes", ""),
            errors=errors,
            action=action,
            selected=not errors,
        )
    if mode["replace_roster"]:
        imported = {normalize_email(row.email) for row in batch.rows.all() if not row.errors}
        for booking in event.bookings.all():
            if booking.normalized_email not in imported:
                ImportRow.objects.create(
                    batch=batch, line_number=0, email=booking.original_email, ticket_count=0,
                    action="remove", selected=True, party_name=booking.party_name,
                )
    error_count = batch.rows.exclude(errors=[]).count()
    batch.summary = {"rows": batch.rows.count(), "errors": error_count, "state": batch.state}
    batch.save(update_fields=["summary"])
    record(actor=actor, organization=event.organization, event=event, operation="import_previewed", object_type="import", object_id=batch.id, request_id=request_id, after=batch.summary)
    return batch


@transaction.atomic
def preview_valid_subset(*, event, batch, actor, request_id):
    event = lock_event(event.id)
    child = ImportBatch.objects.create(
        event=event, uploaded_by=actor, digest=batch.digest + ":valid", mode={**batch.mode, "valid_only": True},
        roster_revision=event.roster_revision, state=ImportBatch.State.PREVIEW, parent=batch,
    )
    for row in batch.rows.filter(errors=[]):
        ImportRow.objects.create(
            batch=child, line_number=row.line_number, email=row.email, ticket_count=row.ticket_count,
            booking_reference=row.booking_reference, party_name=row.party_name, notes=row.notes,
            action=row.action, selected=True,
        )
    child.summary = {"rows": child.rows.count(), "errors": 0, "state": child.state}
    child.save(update_fields=["summary"])
    return child


@transaction.atomic
def commit_import(*, event, batch, actor, request_id):
    event = lock_event(event.id)
    batch = ImportBatch.objects.select_for_update().get(pk=batch.id, event=event)
    if batch.state == ImportBatch.State.COMMITTED:
        return batch
    if batch.roster_revision != event.roster_revision:
        raise Conflict("stale_roster", "The guest list changed after this preview. Upload or preview it again.", revision=event.roster_revision)
    if batch.rows.exclude(errors=[]).exists():
        raise DomainError("import_invalid", "This preview still has errors, so nothing was saved. Preview the valid rows if you want a partial import.")
    if batch.mode.get("replace_roster") and not batch.mode.get("confirm_replace_roster"):
        raise DomainError("confirm_required", "Replacing the whole roster needs an explicit confirmation.")
    for row in batch.rows.filter(selected=True).order_by("line_number"):
        if row.action == "remove":
            booking = Booking.objects.filter(event=event, normalized_email=normalize_email(row.email)).first()
            if booking:
                set_quantity(event=event, booking=booking, target=0, actor=actor, request_id=request_id, bump_revision=False)
            continue
        booking, _created = get_or_create_booking(
            event=event, email=row.email, party_name=row.party_name, booking_reference=row.booking_reference, notes=row.notes,
        )
        current = booking.tickets.filter(status="active").count()
        target = current + row.ticket_count if batch.mode.get("quantity_policy") == "additive" else row.ticket_count
        set_quantity(event=event, booking=booking, target=target, actor=actor, request_id=request_id, bump_revision=False)
    event.refresh_from_db()
    bump(event, roster=True, layout=bool(event.active_publication_id))
    batch.state = ImportBatch.State.COMMITTED
    batch.committed_at = timezone.now()
    batch.summary = {"rows": batch.rows.count(), "errors": 0, "state": batch.state, "roster_revision": event.roster_revision}
    batch.save(update_fields=["state", "committed_at", "summary"])
    record(actor=actor, organization=event.organization, event=event, operation="import_committed", object_type="import", object_id=batch.id, request_id=request_id, after=batch.summary)
    return batch


def error_report_csv(batch):
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["line_number", "email", "ticket_count", "errors"])
    for row in batch.rows.exclude(errors=[]):
        writer.writerow([row.line_number, escape_formula(row.email), row.ticket_count or "", escape_formula("; ".join(row.errors))])
    return buffer.getvalue()
