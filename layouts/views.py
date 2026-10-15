import json

from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from accounts.permissions import can_edit_layout, can_publish, can_view
from core.http import require_login, wants_json
from core.idempotency import execute
from events.views import finish, idempotency_key, load_event, payload
from layouts.services import (
    active_capacity,
    add_chairs,
    create_table,
    duplicate_table as duplicate_table_service,
    layout_payload,
    retire_table as retire_table_service,
    update_geometry,
)


@require_login
@require_http_methods(["GET"])
def editor(request, event_id):
    event = load_event(request, event_id, can_view)
    from guests.models import Booking

    return render(request, "layouts/editor.html", {
        "event": event,
        "layout": layout_payload(event),
        "can_edit": can_edit_layout(request.user, event),
        "capacity": active_capacity(event),
        "bookings": event.bookings.all() if can_edit_layout(request.user, event) else Booking.objects.none(),
    })


@require_login
@require_http_methods(["GET", "PATCH", "POST"])
def layout_api(request, event_id):
    ability = can_edit_layout if request.method != "GET" else can_view
    event = load_event(request, event_id, ability)
    if request.method == "GET":
        return JsonResponse(layout_payload(event))
    data = payload(request)
    key = idempotency_key(request, data)

    def run():
        update_geometry(
            event=event, tables=data.get("tables", []), actor=request.user, request_id=request.request_id,
            expected_version=data.get("expected_version", event.layout_revision), override_reason=data.get("override_reason", ""),
        )
        event.refresh_from_db()
        return layout_payload(event)

    result = execute(organization=event.organization, operation="geometry_update", key=key, payload=data, fn=run)
    return JsonResponse(result.body, status=200 if not result.replayed else 200)


@require_login
@require_http_methods(["POST"])
def tables(request, event_id):
    event = load_event(request, event_id, can_edit_layout)
    data = payload(request)
    key = idempotency_key(request, data) or ""

    def run():
        table = create_table(
            event=event, actor=request.user, request_id=request.request_id,
            shape=data.get("shape", "round"), width=data.get("width", "1.6"), height=data.get("height", "1.6"),
            x=data.get("x") or None, y=data.get("y") or None, rotation=data.get("rotation", 0),
            seats=int(data.get("seats", 8)), label=data.get("label", ""), override_reason=data.get("override_reason", ""),
        )
        event.refresh_from_db()
        body = layout_payload(event)
        body["table_id"] = str(table.id)
        return body

    result = execute(organization=event.organization, operation="table_create", key=key, payload={k: data.get(k) for k in ("shape", "x", "y", "seats", "label")}, fn=run)
    if wants_json(request):
        return JsonResponse(result.body)
    from django.contrib import messages
    messages.success(request, "Table created.")
    return redirect("layout-editor", event_id=event.id)


@require_login
@require_http_methods(["POST"])
def duplicate_table(request, event_id, table_id):
    event = load_event(request, event_id, can_edit_layout)
    duplicate_table_service(event=event, table_id=table_id, actor=request.user, request_id=request.request_id)
    return redirect("layout-editor", event_id=event.id)


@require_login
@require_http_methods(["POST"])
def retire_table(request, event_id, table_id):
    event = load_event(request, event_id, can_edit_layout)
    resolution = json.loads(request.POST.get("resolution") or "{}")
    retire_table_service(event=event, table_id=table_id, actor=request.user, request_id=request.request_id, resolution=resolution)
    return redirect("layout-editor", event_id=event.id)


@require_login
@require_http_methods(["POST"])
def add_chairs_view(request, event_id, table_id):
    event = load_event(request, event_id, can_edit_layout)
    add_chairs(event=event, table_id=table_id, count=int(request.POST.get("count", "1")), actor=request.user, request_id=request.request_id)
    return redirect("layout-editor", event_id=event.id)


@require_login
@require_http_methods(["GET", "POST"])
def publications(request, event_id):
    from layouts.publication_service import diff_publications, publish

    event = load_event(request, event_id, can_view if request.method == "GET" else can_publish)
    if request.method == "POST":
        publication = publish(
            event=event, actor=request.user, request_id=request.request_id,
            acknowledge_unassigned=request.POST.get("acknowledge_unassigned") == "yes",
        )
        return redirect("publications", event_id=event.id)
    publications_list = list(event.publications.all())
    diffs = []
    if len(publications_list) >= 2:
        diffs = diff_publications(publications_list[1], publications_list[0])
    return render(request, "layouts/publications.html", {"event": event, "publications": publications_list, "changed_bookings": diffs})
