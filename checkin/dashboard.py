from datetime import datetime
from zoneinfo import ZoneInfo

from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.db.models import Count

from accounts.permissions import can_checkin
from communications.models import EmailDelivery
from core.errors import DomainError
from events.services import event_metrics
from guests.gala import CAMPAIGN_SUBJECT, ensure_ticket_campaign, smtp_problems
from guests.models import Booking
from layouts.models import EventTable

SENT_STATES = {EmailDelivery.State.SUBMITTED, EmailDelivery.State.DELIVERED}
WAITING_STATES = {EmailDelivery.State.PENDING, EmailDelivery.State.CLAIMED}
FAILED_STATES = {
    EmailDelivery.State.BOUNCED,
    EmailDelivery.State.FAILED,
    EmailDelivery.State.SUPPRESSED,
    EmailDelivery.State.AMBIGUOUS,
}
STATUS_LABELS = {
    "not_sent": "Not sent yet",
    "draft": "Not sent yet",
    "scheduled": "Scheduled",
    "sending": "Sending",
    "sent": "Sent",
    "cancelled": "Cancelled",
}


def door_event(user):
    if not getattr(user, "is_authenticated", False):
        return None
    from events.models import Event
    from guests.gala import GALA_SLUG

    event = Event.objects.filter(slug=GALA_SLUG).select_related("organization").first()
    if event and can_checkin(user, event):
        return event
    return None


def landing_path(user):
    event = door_event(user)
    if event is None:
        return "/events/"
    return f"/events/{event.id}/check-ins/"


def _local(event, value):
    if not value:
        return ""
    return value.astimezone(ZoneInfo(event.timezone))


def schedule_label(event):
    start = _local(event, event.starts_at)
    doors = _local(event, event.doors_open_at)
    return {
        "starts": start.strftime("%A %-d %B %Y, %-I:%M %p") if start else "",
        "doors": doors.strftime("%-I:%M %p") if doors else "",
    }


def _seat_labels(ticket):
    try:
        occupancy = ticket.occupancy
    except ObjectDoesNotExist:
        return "", ""
    return occupancy.seat.table.label, occupancy.seat.label


def table_board(event):
    tables = EventTable.objects.filter(event=event, retired_at__isnull=True).prefetch_related(
        "seats__occupancy__ticket__checkin", "holds"
    )
    rows = []
    for table in tables:
        assigned = arrived = held = 0
        for seat in table.seats.all():
            if seat.retired_at is not None:
                continue
            try:
                occupancy = seat.occupancy
            except ObjectDoesNotExist:
                continue
            if occupancy.ticket_id and occupancy.ticket.status == "active":
                assigned += 1
                try:
                    checkin = occupancy.ticket.checkin
                except ObjectDoesNotExist:
                    checkin = None
                if checkin and checkin.undone_at is None:
                    arrived += 1
            elif occupancy.hold_id and occupancy.hold.released_at is None:
                held += 1
        hold = next((item for item in table.holds.all() if item.released_at is None and item.whole_table), None)
        rows.append(
            {
                "label": table.label,
                "assigned": assigned,
                "arrived": arrived,
                "open": max(sum(1 for seat in table.seats.all() if seat.retired_at is None) - assigned - held, 0),
                "reserved": bool(hold) and assigned == 0,
                "purpose": hold.purpose if hold else "",
                "sort": int(table.label) if str(table.label).isdigit() else 10**6,
            }
        )
    rows.sort(key=lambda row: (row["sort"], row["label"]))
    return rows


def recent_arrivals(event, limit=12):
    from checkin.models import CheckIn

    rows = (
        CheckIn.objects.filter(ticket__booking__event=event, undone_at__isnull=True)
        .select_related("ticket__booking", "ticket__occupancy__seat__table")
        .order_by("-checked_in_at")[:limit]
    )
    arrivals = []
    for row in rows:
        table_label, seat_label = _seat_labels(row.ticket)
        when = _local(event, row.checked_in_at)
        arrivals.append(
            {
                "public_code": row.ticket.public_code or row.ticket.display_name,
                "email": row.ticket.booking.original_email,
                "table_label": table_label,
                "seat_label": seat_label,
                "when": when.strftime("%-I:%M %p") if isinstance(when, datetime) else "",
            }
        )
    return arrivals


def mail_summary(event):
    problems = smtp_problems()
    campaign = event.campaigns.filter(kind="seating", subject=CAMPAIGN_SUBJECT).order_by("created_at").first()
    recipients = Booking.objects.filter(event=event).count()
    pending = sent = failed = 0
    failed_to = []
    status = "not_sent"
    if campaign is not None:
        status = campaign.status
        try:
            audience = campaign.audience
        except ObjectDoesNotExist:
            audience = None
        if audience is not None:
            counts = {row["state"]: row["total"] for row in audience.deliveries.values("state").annotate(total=Count("id"))}
            pending = sum(counts.get(state, 0) for state in WAITING_STATES)
            sent = sum(counts.get(state, 0) for state in SENT_STATES)
            failed = sum(counts.get(state, 0) for state in FAILED_STATES)
            recipients = sum(counts.values()) or recipients
            if failed:
                failed_to = list(
                    audience.deliveries.filter(state__in=FAILED_STATES)
                    .order_by("recipient_email")
                    .values_list("recipient_email", flat=True)[:15]
                )
    return {
        "status": status,
        "status_label": STATUS_LABELS.get(status, status),
        "recipients": recipients,
        "pending": pending,
        "sent": sent,
        "failed": failed,
        "failed_to": failed_to,
        "problems": problems,
        "can_send": status in {"not_sent", "draft"} and not problems and recipients > 0,
    }


def door_context(event):
    metrics = event_metrics(event)
    tables = table_board(event)
    metrics["parties"] = Booking.objects.filter(event=event).count()
    metrics["waiting"] = max(metrics["tickets"] - metrics["checked_in"], 0)
    metrics["open_seats"] = sum(row["open"] for row in tables)
    return {
        "metrics": metrics,
        "tables": tables,
        "recent": recent_arrivals(event),
        "mail": mail_summary(event),
        "schedule": schedule_label(event),
    }


def _kick_mail():
    from communications.tasks import dispatch_due_mail

    dispatch_due_mail.delay()


def queue_ticket_emails(*, event, actor, request_id):
    problems = smtp_problems()
    if problems:
        raise DomainError("smtp_not_ready", " ".join(problems))
    campaign = ensure_ticket_campaign(event, actor, request_id)
    if campaign.status == "cancelled":
        raise DomainError("campaign_closed", "The ticket campaign was cancelled.")
    if campaign.status == "draft":
        from communications.services import queue_campaign

        campaign = queue_campaign(campaign=campaign, actor=actor, request_id=request_id)
        transaction.on_commit(_kick_mail)
    return campaign
