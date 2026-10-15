from django.http import JsonResponse
from django.shortcuts import redirect
from django.views.decorators.http import require_http_methods

from accounts.permissions import can_edit_layout
from core.http import require_login, wants_json
from core.idempotency import execute
from events.views import finish, idempotency_key, load_event, payload
from guests.models import Booking
from seating.services import assign, group_assign, hold_seats, hold_table, release_hold, swap as swap_seats, unassign


def _respond(request, event, result):
    if wants_json(request):
        from layouts.services import layout_payload

        body = dict(result.body)
        event.refresh_from_db()
        body["layout"] = layout_payload(event)
        return JsonResponse(body, status=result.status)
    return redirect("layout-editor", event_id=event.id)


@require_login
@require_http_methods(["POST"])
def holds(request, event_id):
    event = load_event(request, event_id, can_edit_layout)
    data = payload(request)
    key = idempotency_key(request, data)

    def run():
        if data.get("action") == "release":
            return release_hold(event=event, hold_id=data.get("hold_id"), actor=request.user, request_id=request.request_id, reason=data.get("reason", ""))
        if data.get("scope") == "table":
            return hold_table(
                event=event, table_id=data.get("table_id"), purpose=data.get("purpose", "Hold"), actor=request.user,
                request_id=request.request_id, reason=data.get("reason", ""), expires_at=data.get("expires_at") or None,
            )
        seat_ids = data.getlist("seat_ids") if hasattr(data, "getlist") else data.get("seat_ids", [])
        return hold_seats(event=event, seat_ids=seat_ids, purpose=data.get("purpose", "Hold"), actor=request.user, request_id=request.request_id, reason=data.get("reason", ""))

    result = execute(organization=event.organization, operation="hold", key=key, payload={"action": data.get("action"), "table_id": str(data.get("table_id", "")), "purpose": data.get("purpose", "")}, fn=run)
    return _respond(request, event, result)


@require_login
@require_http_methods(["POST"])
def assignments(request, event_id):
    event = load_event(request, event_id, can_edit_layout)
    data = payload(request)
    key = idempotency_key(request, data)

    def run():
        if data.get("action") == "unassign":
            return unassign(event=event, ticket_id=data.get("ticket_id"), actor=request.user, request_id=request.request_id, expected_version=data.get("expected_version"))
        if data.get("action") == "group":
            booking = Booking.objects.get(pk=data.get("booking_id"), event=event)
            return group_assign(
                event=event, booking=booking, table_id=data.get("table_id"), actor=request.user, request_id=request.request_id,
                partial=data.get("partial") in {True, "yes", "true", "on"}, preview=data.get("preview") in {True, "yes", "true", "on"},
                expected_version=data.get("expected_version"),
            )
        return assign(
            event=event, ticket_id=data.get("ticket_id"), seat_id=data.get("seat_id"), actor=request.user,
            request_id=request.request_id, expected_version=data.get("expected_version"), override_reason=data.get("override_reason", ""),
        )

    result = execute(
        organization=event.organization, operation=f"assignment:{data.get('action') or 'assign'}", key=key,
        payload={"ticket_id": str(data.get("ticket_id", "")), "seat_id": str(data.get("seat_id", "")), "booking_id": str(data.get("booking_id", "")), "action": data.get("action", "")},
        fn=run,
    )
    if wants_json(request):
        event.refresh_from_db()
        from layouts.services import layout_payload

        body = dict(result.body)
        body["layout"] = layout_payload(event)
        return JsonResponse(body, status=result.status)
    return redirect("layout-editor", event_id=event.id)


@require_login
@require_http_methods(["POST"])
def swap(request, event_id):
    event = load_event(request, event_id, can_edit_layout)
    data = payload(request)
    key = idempotency_key(request, data)

    def run():
        return swap_seats(
            event=event, seat_a_id=data.get("seat_a"), seat_b_id=data.get("seat_b"), actor=request.user,
            request_id=request.request_id, expected_version=data.get("expected_version"),
        )

    result = execute(organization=event.organization, operation="swap", key=key, payload={"a": str(data.get("seat_a")), "b": str(data.get("seat_b"))}, fn=run)
    if wants_json(request):
        return JsonResponse(result.body, status=result.status)
    return redirect("layout-editor", event_id=event.id)
