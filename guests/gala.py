import csv
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction

from accounts.models import Membership, Organization
from communications.services import create_campaign
from core.errors import DomainError
from events.services import bump, create_event
from guests.models import Booking, Ticket
from guests.services import get_or_create_booking, normalize_email
from layouts.publication_service import publish
from layouts.services import create_table
from seating.models import SeatOccupancy
from seating.services import group_assign, hold_table

GALA_NAME = "Kalenjin Association Gala 2026"
GALA_SLUG = "kalenjin-association-gala-2026"
ORG_NAME = "Kalenjin Community Association & Welfare NSW"
ORG_SLUG = "kalenjin-community-nsw"
TABLE_COUNT = 22
SEATS_PER_TABLE = 10
CAMPAIGN_SUBJECT = "Your Kalenjin Association Gala 2026 ticket"


def ticket_quantity(amount):
    text = (amount or "").strip()
    if not text:
        return 1
    if not text.isdigit():
        raise DomainError("invalid_amount", f"Amount {text} is not a whole number of dollars.")
    value = int(text)
    if value < 100 or value % 100:
        raise DomainError("invalid_amount", f"Amount {text} is not a multiple of the $100 ticket price.")
    return value // 100


def ticket_codes(base, count):
    code = (base or "").strip()
    if not code:
        raise DomainError("invalid_ticket", "Each payment row needs a ticket number.")
    count = int(count)
    if count < 1:
        raise DomainError("invalid_ticket", "A payment must cover at least one ticket.")
    if count == 1:
        return [code]
    return [code] + [f"{code}-{index}" for index in range(2, count + 1)]


def read_payments(path):
    rows = []
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        required = {"Payment ID", "Ticket Number", "Stripe ID", "Amount", "Customer Email"}
        fields = set(reader.fieldnames or [])
        missing = required - fields
        if missing:
            raise DomainError("csv_header", "The payment file is missing: " + ", ".join(sorted(missing)) + ".")
        for line_number, raw in enumerate(reader, start=2):
            email = (raw.get("Customer Email") or "").strip()
            if not email:
                raise DomainError("invalid_email", f"Line {line_number} has no email address.")
            rows.append(
                {
                    "line": line_number,
                    "payment_id": (raw.get("Payment ID") or "").strip(),
                    "ticket_number": (raw.get("Ticket Number") or "").strip(),
                    "source": (raw.get("Source") or "").strip(),
                    "stripe_id": (raw.get("Stripe ID") or "").strip(),
                    "amount": (raw.get("Amount") or "").strip(),
                    "email": email,
                }
            )
    if not rows:
        raise DomainError("csv_empty", "The payment file has no ticket rows.")
    return rows


def expected_codes(rows):
    codes = []
    seen = set()
    for row in rows:
        for code in ticket_codes(row["ticket_number"], ticket_quantity(row["amount"])):
            if code in seen:
                raise DomainError("duplicate_ticket", f"Ticket number {code} is repeated.")
            seen.add(code)
            codes.append(code)
    return codes


def group_payment_rows(rows):
    parent = list(range(len(rows)))

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left, right):
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    by_email = {}
    by_stripe = {}
    for index, row in enumerate(rows):
        email = normalize_email(row["email"])
        if email in by_email:
            union(index, by_email[email])
        else:
            by_email[email] = index
        stripe_id = row.get("stripe_id") or ""
        if not stripe_id:
            continue
        if stripe_id in by_stripe:
            union(index, by_stripe[stripe_id])
        else:
            by_stripe[stripe_id] = index
    groups = {}
    for index, row in enumerate(rows):
        groups.setdefault(find(index), []).append(row)
    return list(groups.values())


def _logo_path():
    return Path(settings.BASE_DIR) / "core" / "static" / "brand" / "kcaw-logo.png"


def ensure_gala_event(actor):
    organization, _created = Organization.objects.get_or_create(
        slug=ORG_SLUG,
        defaults={"name": ORG_NAME},
    )
    if organization.name != ORG_NAME:
        organization.name = ORG_NAME
        organization.save(update_fields=["name"])
    Membership.objects.get_or_create(
        user=actor,
        organization=organization,
        defaults={"role": Membership.Role.OWNER},
    )
    event = organization.events.filter(slug=GALA_SLUG).first()
    if event is None:
        event = create_event(
            actor=actor,
            organization=organization,
            data={
                "name": GALA_NAME,
                "description": (
                    "Kibagenge ko Kimnon. Celebrating our people. Honouring our heritage. "
                    "Building our future. One People. One Voice. One Future."
                ),
                "venue_name": "Assyrian Sports and Cultural Club",
                "address_line1": "52-54 Stanbrook St",
                "locality": "Fairfield Heights",
                "region": "NSW",
                "postal_code": "2165",
                "country": "Australia",
                "timezone": "Australia/Sydney",
                "starts_at": "2026-10-17T17:00",
                "ends_at": "2026-10-17T22:00",
                "doors_open_at": "2026-10-17T16:30",
                "initial_table_count": 0,
                "default_seats_per_table": SEATS_PER_TABLE,
            },
            request_id="load-gala",
        )
    logo = _logo_path()
    if logo.exists() and not event.logo:
        event.logo.save("kcaw-logo.png", ContentFile(logo.read_bytes()), save=True)
    return event


@transaction.atomic
def import_payments(event, actor, rows, request_id):
    codes = expected_codes(rows)
    existing = set(
        Ticket.objects.filter(booking__event=event, status=Ticket.Status.ACTIVE)
        .exclude(public_code="")
        .values_list("public_code", flat=True)
    )
    if existing == set(codes):
        return {"created": 0, "unchanged": True}
    if existing:
        raise DomainError(
            "roster_exists",
            "This event already has tickets that do not match the payment file, so another set was not created.",
        )
    grouped = {}
    for row in rows:
        grouped.setdefault(normalize_email(row["email"]), []).append(row)
    created = 0
    for email, email_rows in grouped.items():
        email_rows = sorted(email_rows, key=lambda item: item["ticket_number"])
        notes = "\n".join(
            f"{row['payment_id']} {row['stripe_id']} amount={row['amount'] or 'manual'} {row['ticket_number']}"
            for row in email_rows
        )
        booking, _unused = get_or_create_booking(
            event=event,
            email=email_rows[0]["email"],
            party_name=email.split("@", 1)[0][:200],
            booking_reference=(email_rows[0]["payment_id"] or "")[:120],
            notes=notes,
            actor=actor,
            request_id=request_id,
        )
        sequence = booking.tickets.count()
        for row in email_rows:
            for code in ticket_codes(row["ticket_number"], ticket_quantity(row["amount"])):
                sequence += 1
                Ticket.objects.create(
                    booking=booking,
                    sequence=sequence,
                    public_code=code,
                    display_name=code,
                    display_name_custom=True,
                )
                created += 1
    bump(event, roster=True)
    return {"created": created, "unchanged": False}


def place_tables(event, actor, request_id, table_count=TABLE_COUNT, seats=SEATS_PER_TABLE):
    room = event.rooms.first()
    room.width_m = Decimal("80")
    room.height_m = Decimal("48")
    room.name = "Main hall"
    room.save(update_fields=["width_m", "height_m", "name"])
    expected = {str(number) for number in range(1, table_count + 1)}
    existing = set(event.tables.filter(retired_at__isnull=True).values_list("label", flat=True))
    extra = existing - expected
    if extra:
        raise DomainError("unexpected_tables", "The room already has tables that are not part of the gala plan.")
    spacing = Decimal("6")
    columns = 6
    for index in range(table_count):
        label = str(index + 1)
        if label in existing:
            continue
        row, column = divmod(index, columns)
        create_table(
            event=event,
            actor=actor,
            request_id=request_id,
            seats=seats,
            label=label,
            x=Decimal("4") + Decimal(column) * spacing,
            y=Decimal("4") + Decimal(row) * spacing,
            override_reason="Gala floor plan",
        )


def _party_bookings(event, rows):
    parties = []
    for group in group_payment_rows(rows):
        emails = []
        seen = set()
        for row in group:
            email = normalize_email(row["email"])
            if email not in seen:
                seen.add(email)
                emails.append(email)
        bookings = list(Booking.objects.filter(event=event, normalized_email__in=emails))
        if len(bookings) != len(emails):
            raise DomainError("missing_booking", "A payment email was not imported before seating.")
        parties.append(bookings)
    parties.sort(key=lambda bookings: (-_party_size(bookings), bookings[0].normalized_email))
    return parties


def _party_size(bookings):
    return Ticket.objects.filter(booking__in=bookings, status=Ticket.Status.ACTIVE).count()


def _open_tables(event):
    tables = [table for table in event.tables.filter(retired_at__isnull=True) if table.label != "1"]
    tables.sort(key=lambda table: int(table.label))
    return tables


def _free_seats(table):
    return table.seats.filter(availability="active", retired_at__isnull=True).exclude(occupancy__isnull=False).count()


def assign_parties(event, actor, rows, request_id):
    table_one = event.tables.get(label="1", event=event, retired_at__isnull=True)
    held = SeatOccupancy.objects.filter(seat__table=table_one, hold__isnull=False).exists()
    assigned = SeatOccupancy.objects.filter(seat__table=table_one, ticket__isnull=False).exists()
    if assigned:
        raise DomainError("table_one_assigned", "Table 1 is reserved and cannot hold guests.")
    if not held:
        hold_table(
            event=event,
            table_id=table_one.id,
            purpose="Reserved",
            actor=actor,
            request_id=request_id,
            reason="Table 1 is held for the association.",
        )
    tables = _open_tables(event)
    free = {table.id: _free_seats(table) for table in tables}
    by_id = {table.id: table for table in tables}
    for bookings in _party_bookings(event, rows):
        tickets = list(Ticket.objects.filter(booking__in=bookings, status=Ticket.Status.ACTIVE).select_related("booking"))
        seated_tables = set()
        unassigned = []
        for ticket in tickets:
            occupancy = SeatOccupancy.objects.filter(ticket=ticket).select_related("seat").first()
            if occupancy:
                seated_tables.add(occupancy.seat.table_id)
            else:
                unassigned.append(ticket)
        if not unassigned:
            continue
        if len(seated_tables) > 1:
            raise DomainError("party_split", "A party is already split across tables.")
        needed = len(unassigned)
        if seated_tables:
            target_id = next(iter(seated_tables))
        else:
            target_id = next((table_id for table_id, count in ((table.id, free[table.id]) for table in tables) if count >= needed), None)
            if target_id is None:
                raise DomainError("insufficient_tables", f"No table has {needed} open seats for this party.")
            free[target_id] -= needed
        target = by_id.get(target_id) or event.tables.get(pk=target_id)
        pending_bookings = {ticket.booking_id: ticket.booking for ticket in unassigned}
        for booking in pending_bookings.values():
            group_assign(
                event=event,
                booking=booking,
                table_id=target.id,
                actor=actor,
                request_id=request_id,
            )


def publish_gala(event, actor, request_id):
    event.refresh_from_db()
    if Ticket.objects.filter(booking__event=event, status=Ticket.Status.ACTIVE, occupancy__isnull=True).exists():
        raise DomainError("unassigned_tickets", "Some tickets still have no seat.")
    if event.active_publication_id and not event.republish_required:
        return event.active_publication
    return publish(event=event, actor=actor, request_id=request_id)


def ensure_ticket_campaign(event, actor, request_id):
    existing = event.campaigns.filter(kind="seating", subject=CAMPAIGN_SUBJECT).order_by("created_at").first()
    if existing:
        return existing
    return create_campaign(
        event=event,
        actor=actor,
        kind="seating",
        subject=CAMPAIGN_SUBJECT,
        audience_filter={"kind": "all"},
        request_id=request_id,
    )


def smtp_problems():
    problems = []
    if not settings.PUBLIC_BASE_URL.startswith("https://"):
        problems.append("Set PUBLIC_BASE_URL to the public https address before sending.")
    if not settings.EMAIL_HOST or settings.EMAIL_HOST == "maildev":
        problems.append("Set EMAIL_HOST to the real SMTP server before sending.")
    if not settings.EMAIL_HOST_PASSWORD:
        problems.append("Set EMAIL_HOST_PASSWORD or SENDGRID_API_KEY before sending.")
    sender = settings.DEFAULT_FROM_EMAIL or ""
    if not sender or sender.endswith("@example.test"):
        problems.append("Set DEFAULT_FROM_EMAIL to the real sender address before sending.")
    return problems


def send_ticket_campaign(event, actor, request_id):
    problems = smtp_problems()
    if problems:
        raise DomainError("smtp_not_ready", " ".join(problems))
    campaign = ensure_ticket_campaign(event, actor, request_id)
    from communications.models import EmailDelivery
    from communications.services import dispatch_pending, queue_campaign

    if campaign.status == "draft":
        queue_campaign(campaign=campaign, actor=actor, request_id=request_id)
    import time

    for _attempt in range(6):
        dispatch_pending(limit=50)
        pending = EmailDelivery.objects.filter(audience__campaign=campaign, state="pending").count()
        if pending == 0:
            break
        time.sleep(61)
    return campaign
