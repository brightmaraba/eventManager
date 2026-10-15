import json
import uuid

from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from accounts.permissions import (
    can_checkin,
    can_communicate,
    can_edit_layout,
    can_export,
    can_import,
    can_manage_event,
    can_publish,
    can_view,
)
from core.errors import Conflict, DomainError, NotFound
from core.http import require_login, wants_json
from core.idempotency import execute
from events.models import Event


def load_event(request, event_id, ability=can_view):
    event = Event.objects.filter(pk=event_id).select_related("organization").first()
    if event is None or not can_view(request.user, event):
        raise NotFound()
    if not ability(request.user, event):
        from core.errors import Denied

        raise Denied()
    request.session["organization_id"] = str(event.organization_id)
    return event


def payload(request):
    if request.content_type == "application/json":
        try:
            return json.loads(request.body.decode() or "{}")
        except json.JSONDecodeError as exc:
            raise DomainError("invalid_json", "The request body is not valid JSON.") from exc
    return request.POST


def idempotency_key(request, data):
    return (request.headers.get("Idempotency-Key") or data.get("idempotency_key") or "").strip()


def finish(request, result, target):
    from core.http import json_result

    if wants_json(request):
        return json_result(result)
    messages.success(request, "Saved.")
    return redirect(target)


def show_schedule_error(form, exc):
    if isinstance(exc, Conflict):
        raise exc
    if exc.field_errors:
        for field, message in exc.field_errors.items():
            form.add_error(field if field in form.fields else None, message)
    else:
        form.add_error(None, exc.message)


@require_login
@require_http_methods(["GET"])
def event_list(request):
    organization = getattr(request, "organization", None)
    events = Event.objects.filter(organization__memberships__user=request.user)
    granted = Event.objects.filter(grants__user=request.user)
    events = (events | granted).distinct()
    if request.user.is_platform_admin and organization:
        events = Event.objects.filter(organization=organization)
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    venue = request.GET.get("venue", "").strip()
    if query:
        events = events.filter(name__icontains=query)
    if status:
        events = events.filter(status=status)
    if venue:
        events = events.filter(venue_name__icontains=venue)
    return render(request, "events/list.html", {"events": events.order_by("-starts_at"), "statuses": Event.Status.choices})


@require_login
@require_http_methods(["GET", "POST"])
def event_create(request):
    from accounts.models import Membership
    from events.forms import EventForm
    from events.services import create_event

    organization = request.organization
    if organization is None:
        return redirect("organization-select")
    allowed = request.user.is_platform_admin or Membership.objects.filter(
        user=request.user, organization=organization,
        role__in=[Membership.Role.OWNER, Membership.Role.EVENT_ADMINISTRATOR],
    ).exists()
    if not allowed:
        raise NotFound()
    form = EventForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        key = idempotency_key(request, request.POST) or str(uuid.uuid4())

        def run():
            event = create_event(actor=request.user, organization=organization, data=data, request_id=request.request_id)
            if data.get("logo"):
                from events.services import save_image

                save_image(actor=request.user, event=event, uploaded=data["logo"], field="logo", request_id=request.request_id)
            return {"event_id": str(event.id)}

        try:
            result = execute(organization=organization, operation="event_create", key=key, payload={"name": data["name"], "starts_at": str(data["starts_at"])}, fn=run)
        except DomainError as exc:
            show_schedule_error(form, exc)
        else:
            messages.success(request, "Event created.")
            return redirect("event-detail", event_id=result.body["event_id"])
    return render(request, "events/form.html", {"form": form, "mode": "create"})


@require_login
@require_http_methods(["GET"])
def event_detail(request, event_id):
    from events.services import event_form_data, event_metrics

    event = load_event(request, event_id)
    return render(request, "events/detail.html", {
        "event": event,
        "metrics": event_metrics(event),
        "local": event_form_data(event),
        "can_manage": can_manage_event(request.user, event),
        "can_layout": can_edit_layout(request.user, event),
        "can_import": can_import(request.user, event),
        "can_publish": can_publish(request.user, event),
        "can_mail": can_communicate(request.user, event),
        "can_checkin": can_checkin(request.user, event),
        "can_export": can_export(request.user, event),
    })


@require_login
@require_http_methods(["GET", "POST"])
def event_edit(request, event_id):
    from events.forms import EventForm
    from events.services import event_form_data, save_image, update_event

    event = load_event(request, event_id, can_manage_event)
    initial = event_form_data(event)
    form = EventForm(request.POST or None, request.FILES or None, initial=None if request.method == "POST" else initial)
    if request.method == "POST" and form.is_valid():
        try:
            update_event(actor=request.user, event=event, data=form.cleaned_data, request_id=request.request_id)
        except DomainError as exc:
            show_schedule_error(form, exc)
        else:
            if form.cleaned_data.get("logo"):
                save_image(actor=request.user, event=event, uploaded=form.cleaned_data["logo"], field="logo", request_id=request.request_id)
            messages.success(request, "Event saved.")
            return redirect("event-detail", event_id=event.id)
    return render(request, "events/form.html", {"form": form, "mode": "edit", "event": event})


@require_login
@require_http_methods(["POST"])
def event_action(request, event_id, action):
    from events.services import change_status, duplicate_event, purge_personal_data

    event = load_event(request, event_id, can_manage_event)
    reason = request.POST.get("reason", "")
    if action == "duplicate":
        copy = duplicate_event(actor=request.user, event=event, name=request.POST.get("name", ""), request_id=request.request_id)
        return redirect("event-detail", event_id=copy.id)
    if action == "purge":
        from accounts.permissions import can_manage_members

        if not can_manage_members(request.user, event.organization):
            from core.errors import Denied
            raise Denied()
        purge_personal_data(actor=request.user, event=event, reason=reason, request_id=request.request_id)
        messages.success(request, "Personal data was removed.")
        return redirect("event-detail", event_id=event.id)
    change_status(actor=request.user, event=event, action=action, reason=reason, request_id=request.request_id)
    messages.success(request, "Event updated.")
    return redirect("event-detail", event_id=event.id)
