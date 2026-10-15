from django.shortcuts import render
from django.views.decorators.http import require_GET

from accounts.permissions import throttle
from core.errors import DomainError, NotFound
from core.http import error_response
from guests.models import Ticket
from guests.tokens import resolve_token


@require_GET
def guest_seating(request, token):
    try:
        throttle(f"guest:{request.META.get('REMOTE_ADDR', 'unknown')}", 60, 60)
        access = resolve_token(token, "booking_view")
        if access is None or access.booking_id is None:
            raise NotFound()
        booking = access.booking
        event = booking.event
        publication = event.active_publication
        seats = []
        if publication:
            live_ids = set(str(value) for value in booking.tickets.filter(status=Ticket.Status.ACTIVE).values_list("id", flat=True))
            for item in publication.snapshot.get("assignments", []):
                if item.get("booking_id") == str(booking.id) and item.get("ticket_id") in live_ids:
                    seats.append(item)
        return render(request, "guests/seating.html", {
            "event": event,
            "booking": booking,
            "seats": seats,
            "pending": not seats,
            "publication_number": publication.number if publication else None,
        })
    except DomainError as exc:
        return error_response(request, exc)
