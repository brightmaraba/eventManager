from django.contrib import messages
from django.db.models import Q
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from accounts.permissions import can_checkin, can_communicate, throttle
from checkin.dashboard import door_context, queue_ticket_emails
from checkin.services import check_in, check_in_token, party_progress, undo_check_in
from core.errors import DomainError, NotFound
from core.http import require_login
from events.views import load_event
from guests.models import Booking
from guests.tokens import issue_checkin_token


def arrival_message(result):
    where = (
        f"Table {result['table_label']}, seat {result['seat_label']}"
        if result.get("table_label")
        else "No seat assigned"
    )
    state = "Already checked in" if result["already_checked_in"] else "Checked in"
    code = result.get("public_code") or result.get("display_name") or "Ticket"
    email = result.get("email") or ""
    return f"{state}: {code} · {email} · {where}."


@require_login
@require_http_methods(["GET", "POST"])
def checkins(request, event_id):
    event = load_event(request, event_id, can_checkin)
    results = []
    progress = None
    message = ""
    arrival = None
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "search":
                query = request.POST.get("q", "").strip()
                results = list(
                    event.bookings.filter(
                        Q(party_name__icontains=query)
                        | Q(original_email__icontains=query)
                        | Q(booking_reference__icontains=query)
                        | Q(tickets__public_code__icontains=query)
                    ).distinct()[:20]
                )
            elif action == "arrive":
                arrival = check_in(
                    event=event,
                    ticket_id=request.POST.get("ticket_id"),
                    actor=request.user,
                    request_id=request.request_id,
                    device_ref=request.POST.get("device", ""),
                )
                message = arrival_message(arrival)
            elif action == "undo":
                undo_check_in(
                    event=event,
                    ticket_id=request.POST.get("ticket_id"),
                    actor=request.user,
                    request_id=request.request_id,
                    reason=request.POST.get("reason", ""),
                )
                message = "Check-in undone."
            elif action == "scan":
                throttle(f"scan:{request.META.get('REMOTE_ADDR', '')}", 30, 60)
                arrival = check_in_token(
                    raw_token=request.POST.get("token", ""),
                    actor=request.user,
                    request_id=request.request_id,
                    device_ref="scanner",
                )
                message = arrival_message(arrival)
            elif action == "qr":
                from guests.models import Ticket

                ticket = Ticket.objects.get(pk=request.POST.get("ticket_id"), booking__event=event)
                raw = issue_checkin_token(ticket)
                message = f"/checkin/t/{raw}/"
            elif action == "send":
                if not can_communicate(request.user, event):
                    raise DomainError("denied", "You do not have permission to send ticket emails.")
                if request.POST.get("confirm") != "yes":
                    message = "Tick the confirmation before sending ticket emails."
                else:
                    queue_ticket_emails(event=event, actor=request.user, request_id=request.request_id)
                    messages.success(request, "Ticket emails are queued. About 60 leave each minute.")
                    return redirect("checkins", event_id=event.id)
        except NotFound as exc:
            message = exc.message
        except DomainError as exc:
            message = exc.message
    query = request.GET.get("booking")
    if query:
        booking = Booking.objects.filter(pk=query, event=event).first()
        if booking:
            progress = party_progress(booking)
            results = [booking]
    context = door_context(event)
    context.update(
        {
            "event": event,
            "results": results,
            "progress": progress,
            "message": message,
            "arrival": arrival,
            "can_mail": can_communicate(request.user, event),
        }
    )
    return render(request, "checkin/desk.html", context)


@require_login
@require_http_methods(["GET", "POST"])
def scan_code(request, token):
    throttle(f"scan:{request.META.get('REMOTE_ADDR', '')}", 30, 60)
    if request.method == "POST":
        try:
            result = check_in_token(raw_token=token, actor=request.user, request_id=request.request_id, device_ref="qr")
        except NotFound as exc:
            return render(request, "checkin/scan.html", {"result": None, "token": "", "message": exc.message})
        return render(request, "checkin/scan.html", {"result": result, "token": "", "message": arrival_message(result)})
    return render(request, "checkin/scan.html", {"result": None, "token_present": True, "message": ""})
