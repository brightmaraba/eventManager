from datetime import timedelta

from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone
from zoneinfo import ZoneInfo

from guests.models import Ticket
from guests.tokens import issue_booking_token, issue_checkin_token


def event_context(event, booking, publication, *, issue_checkin=False):
    zone = ZoneInfo(event.timezone)
    starts = event.starts_at.astimezone(zone)
    seats = []
    pending = True
    if publication:
        for item in publication.snapshot.get("assignments", []):
            if item["booking_id"] != str(booking.id):
                continue
            ticket = Ticket.objects.filter(pk=item["ticket_id"], status=Ticket.Status.ACTIVE).first()
            if not ticket:
                continue
            seat = dict(item)
            seat["public_code"] = ticket.public_code or item.get("display_name") or ""
            seat["checkin_url"] = ""
            if issue_checkin:
                raw = issue_checkin_token(ticket)
                seat["checkin_url"] = f"{settings.PUBLIC_BASE_URL}/checkin/t/{raw}/"
            seats.append(seat)
        pending = not seats
    address = ", ".join(part for part in [event.venue_name, event.address_line1, event.locality, event.region, event.postal_code, event.country] if part)
    return {
        "event_name": event.name,
        "when": starts.strftime("%A %d %B %Y %H:%M"),
        "timezone": event.timezone,
        "venue": address,
        "party_name": booking.party_name or booking.original_email,
        "ticket_total": booking.tickets.filter(status=Ticket.Status.ACTIVE).count(),
        "seats": seats,
        "pending": pending,
        "contact_name": event.contact_name,
        "contact_email": event.contact_email,
        "accessibility_notes": event.accessibility_notes,
        "guest_url": "",
        "logo_cid": "kcaw-logo",
    }


def render_message(campaign, booking, publication, *, issue_link=False):
    context = event_context(
        campaign.event,
        booking,
        publication,
        issue_checkin=issue_link and campaign.kind == "seating",
    )
    if issue_link and campaign.kind in {"seating", "changes", "reminder"}:
        raw = issue_booking_token(booking)
        context["guest_url"] = f"{settings.PUBLIC_BASE_URL}/guest/{raw}/"
    html = render_to_string(f"communications/email/{campaign.kind}.html", context)
    text = render_to_string(f"communications/email/{campaign.kind}.txt", context)
    subject = campaign.subject or f"{campaign.event.name}: {campaign.get_kind_display()}"
    return subject, html, text


def calendar_ics(event):
    stamp = timezone.now().strftime("%Y%m%dT%H%M%SZ")
    start = event.starts_at.strftime("%Y%m%dT%H%M%SZ")
    end = event.ends_at.strftime("%Y%m%dT%H%M%SZ")
    summary = event.name.replace("\n", " ")
    return (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Event Tables//EN\r\n"
        f"BEGIN:VEVENT\r\nUID:{event.id}@example.test\r\nDTSTAMP:{stamp}\r\n"
        f"DTSTART:{start}\r\nDTEND:{end}\r\nSUMMARY:{summary}\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    )
