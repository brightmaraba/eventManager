from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from accounts.permissions import can_import, can_manage_event, can_view
from core.http import require_login
from events.views import load_event
from guests.imports import commit_import, error_report_csv, preview_import, preview_valid_subset
from guests.models import ImportBatch, Ticket
from guests.services import update_attendee


@require_login
@require_http_methods(["GET", "POST"])
def imports(request, event_id):
    event = load_event(request, event_id, can_import if request.method == "POST" else can_view)
    if request.method == "POST" and request.FILES.get("csv"):
        batch = preview_import(
            event=event, actor=request.user, raw=request.FILES["csv"].read(), filename=request.FILES["csv"].name,
            request_id=request.request_id,
            duplicate_policy=request.POST.get("duplicate_policy", "reject"),
            quantity_policy=request.POST.get("quantity_policy", "replace"),
            replace_roster=request.POST.get("replace_roster") == "yes",
            confirm_replace_roster=request.POST.get("confirm_replace_roster") == "yes",
            force_new=request.POST.get("force_new") == "yes",
        )
        return redirect("import-detail", event_id=event.id, batch_id=batch.id)
    return render(request, "guests/imports/upload.html", {"event": event, "batches": event.imports.all()[:20]})


@require_login
@require_http_methods(["GET"])
def import_detail(request, event_id, batch_id):
    event = load_event(request, event_id, can_view)
    batch = ImportBatch.objects.get(pk=batch_id, event=event)
    return render(request, "guests/imports/preview.html", {"event": event, "batch": batch, "rows": batch.rows.all()})


@require_login
@require_http_methods(["POST"])
def import_commit(request, event_id, batch_id):
    event = load_event(request, event_id, can_import)
    batch = ImportBatch.objects.get(pk=batch_id, event=event)
    commit_import(event=event, batch=batch, actor=request.user, request_id=request.request_id)
    return redirect("import-detail", event_id=event.id, batch_id=batch.id)


@require_login
@require_http_methods(["POST"])
def import_valid(request, event_id, batch_id):
    event = load_event(request, event_id, can_import)
    batch = ImportBatch.objects.get(pk=batch_id, event=event)
    child = preview_valid_subset(event=event, batch=batch, actor=request.user, request_id=request.request_id)
    return redirect("import-detail", event_id=event.id, batch_id=child.id)


@require_login
@require_http_methods(["GET"])
def import_errors(request, event_id, batch_id):
    event = load_event(request, event_id, can_import)
    batch = ImportBatch.objects.get(pk=batch_id, event=event)
    response = HttpResponse(error_report_csv(batch), content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="import-errors.csv"'
    return response


@require_login
@require_http_methods(["GET"])
def bookings(request, event_id):
    event = load_event(request, event_id, can_view)
    query = request.GET.get("q", "").strip()
    rows = event.bookings.all()
    if query:
        rows = rows.filter(party_name__icontains=query) | rows.filter(original_email__icontains=query)
    return render(request, "guests/bookings.html", {"event": event, "bookings": rows.distinct()})


@require_login
@require_http_methods(["GET", "POST"])
def ticket_edit(request, event_id, ticket_id):
    event = load_event(request, event_id, can_manage_event)
    ticket = Ticket.objects.select_related("booking").get(pk=ticket_id, booking__event=event)
    if request.method == "POST":
        update_attendee(event=event, ticket=ticket, display_name=request.POST.get("display_name", ""), actor=request.user, request_id=request.request_id)
        return redirect("bookings", event_id=event.id)
    return render(request, "guests/ticket.html", {"event": event, "ticket": ticket})
