from django.db.models import Q
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from accounts.permissions import can_checkin, throttle
from checkin.services import check_in, check_in_token, party_progress, undo_check_in
from core.http import require_login
from events.views import load_event
from guests.models import Booking
from guests.tokens import issue_checkin_token


@require_login
@require_http_methods(["GET", "POST"])
def checkins(request, event_id):
    event = load_event(request, event_id, can_checkin)
    results = []
    progress = None
    message = ""
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "search":
            query = request.POST.get("q", "").strip()
            results = event.bookings.filter(Q(party_name__icontains=query) | Q(original_email__icontains=query) | Q(booking_reference__icontains=query))[:20]
        elif action == "arrive":
            result = check_in(event=event, ticket_id=request.POST.get("ticket_id"), actor=request.user, request_id=request.request_id, device_ref=request.POST.get("device", ""))
            message = "Already checked in." if result["already_checked_in"] else "Checked in."
        elif action == "undo":
            undo_check_in(event=event, ticket_id=request.POST.get("ticket_id"), actor=request.user, request_id=request.request_id, reason=request.POST.get("reason", ""))
            message = "Check-in undone."
        elif action == "scan":
            throttle(f"scan:{request.META.get('REMOTE_ADDR', '')}", 30, 60)
            result = check_in_token(raw_token=request.POST.get("token", ""), actor=request.user, request_id=request.request_id, device_ref="scanner")
            message = "Already checked in." if result["already_checked_in"] else "Checked in."
        elif action == "qr":
            from guests.models import Ticket

            ticket = Ticket.objects.get(pk=request.POST.get("ticket_id"), booking__event=event)
            raw = issue_checkin_token(ticket)
            message = f"/checkin/t/{raw}/"
    query = request.GET.get("booking")
    if query:
        booking = Booking.objects.filter(pk=query, event=event).first()
        if booking:
            progress = party_progress(booking)
            results = [booking]
    return render(request, "checkin/desk.html", {"event": event, "results": results, "progress": progress, "message": message})


@require_login
@require_http_methods(["GET", "POST"])
def scan_code(request, token):
    throttle(f"scan:{request.META.get('REMOTE_ADDR', '')}", 30, 60)
    if request.method == "POST":
        result = check_in_token(raw_token=token, actor=request.user, request_id=request.request_id, device_ref="qr")
        return render(request, "checkin/scan.html", {"result": result, "token": ""})
    return render(request, "checkin/scan.html", {"result": None, "token_present": True})
