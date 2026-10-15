import csv
from datetime import timedelta
from io import StringIO

from django.core.files.base import ContentFile
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone

from accounts.permissions import can_export, can_view_accessibility
from audit.services import record
from core.errors import Denied, NotFound
from guests.imports import escape_formula
from guests.models import Ticket
from layouts.publication_service import build_snapshot
from reports.models import ExportJob
from seating.models import SeatOccupancy


def _snapshot(event, publication_id=None):
    if publication_id:
        publication = event.publications.filter(pk=publication_id).first()
        if publication is None:
            raise NotFound()
        return publication.snapshot, f"Publication {publication.number}", publication.id
    if event.active_publication_id:
        publication = event.active_publication
        return publication.snapshot, f"Publication {publication.number}", publication.id
    return build_snapshot(event), "Current draft", None


def print_context(event, kind, *, public_variant=True, publication_id=None, paper="a4", orientation="landscape", fit_mode="fit"):
    snapshot, label, pub_id = _snapshot(event, publication_id)
    show_email = not public_variant
    rows = []
    for item in snapshot.get("assignments", []):
        ticket = Ticket.objects.filter(pk=item["ticket_id"]).select_related("booking").first()
        rows.append({
            **item,
            "email": ticket.booking.original_email if ticket and show_email else "",
            "notes": ticket.booking.notes if ticket and show_email else "",
            "accessibility": ticket.booking.accessibility_notes if ticket and not public_variant else "",
        })
    if kind == "accessibility" and public_variant:
        rows = []
    return {
        "event": event,
        "kind": kind,
        "snapshot": snapshot,
        "rows": sorted(rows, key=lambda row: (row.get("table_label", ""), row.get("seat_label", ""), row.get("party_name", ""))),
        "alpha_rows": sorted(rows, key=lambda row: (row.get("party_name", ""), row.get("display_name", ""))),
        "label": label,
        "generated_at": timezone.now(),
        "public_variant": public_variant,
        "paper": paper,
        "orientation": orientation,
        "fit_mode": fit_mode,
        "show_email": show_email,
    }


def render_html(event, kind, **kwargs):
    context = print_context(event, kind, **kwargs)
    return render_to_string("reports/print.html", context)


def _safe_fetcher(url, timeout=10, ssl_context=None):
    if url.startswith("data:"):
        from weasyprint import default_url_fetcher

        return default_url_fetcher(url, timeout=timeout, ssl_context=ssl_context)
    raise ValueError("PDF rendering cannot fetch remote or local files.")


def html_to_pdf(html):
    from pathlib import Path

    from django.conf import settings
    from weasyprint import CSS, HTML

    css_path = Path(settings.BASE_DIR) / "reports" / "static" / "reports" / "print.css"
    return HTML(string=html, url_fetcher=_safe_fetcher).write_pdf(stylesheets=[CSS(filename=str(css_path))])


@transaction.atomic
def queue_pdf(*, event, actor, request_id, kind, public_variant=True, paper="a4", orientation="landscape", fit_mode="fit", publication_id=None):
    if kind == "accessibility" and not can_view_accessibility(actor, event):
        raise Denied("Accessibility reports are limited to event administrators.")
    if not can_export(actor, event):
        raise Denied()
    job = ExportJob.objects.create(
        event=event, requester=actor, kind=kind, file_format="pdf", public_variant=public_variant,
        publication_id=publication_id, paper=paper, orientation=orientation, fit_mode=fit_mode,
        expires_at=timezone.now() + timedelta(days=event.organization.retention_report_days),
    )
    record(actor=actor, organization=event.organization, event=event, operation="export_queued", object_type="export", object_id=job.id, request_id=request_id, after={"kind": kind})
    return job


def render_job(job_id):
    job = ExportJob.objects.select_related("event__organization", "requester").get(pk=job_id)
    if not can_export(job.requester, job.event):
        job.state = ExportJob.State.DENIED
        job.save(update_fields=["state"])
        return job
    try:
        html = render_html(
            job.event, job.kind, public_variant=job.public_variant, publication_id=job.publication_id,
            paper=job.paper, orientation=job.orientation, fit_mode=job.fit_mode,
        )
        pdf = html_to_pdf(html)
        job.artifact.save(f"{job.id}.pdf", ContentFile(pdf), save=False)
        job.snapshot_label = "pdf"
        job.state = ExportJob.State.READY
        job.save(update_fields=["artifact", "snapshot_label", "state"])
    except Exception as exc:
        job.state = ExportJob.State.FAILED
        job.error = str(exc)[:240]
        job.save(update_fields=["state", "error"])
    return job


def assignments_csv(event, *, include_email, actor):
    if include_email and not can_export(actor, event):
        raise Denied()
    snapshot, label, _pub = _snapshot(event)
    buffer = StringIO()
    writer = csv.writer(buffer)
    header = ["party_name", "display_name", "table", "seat", "snapshot"]
    if include_email:
        header.insert(1, "email")
    writer.writerow(header)
    for item in snapshot.get("assignments", []):
        ticket = Ticket.objects.filter(pk=item["ticket_id"]).select_related("booking").first()
        row = [
            escape_formula(item.get("party_name", "")),
            escape_formula(item.get("display_name", "")),
            escape_formula(item.get("table_label", "")),
            escape_formula(item.get("seat_label", "")),
            escape_formula(label),
        ]
        if include_email:
            email = ticket.booking.original_email if ticket else ""
            row.insert(1, escape_formula(email))
        writer.writerow(row)
    unassigned = SeatOccupancy.objects.none()
    for item in snapshot.get("unassigned", []):
        ticket = Ticket.objects.filter(pk=item["ticket_id"]).select_related("booking").first()
        row = [escape_formula(ticket.booking.party_name if ticket else ""), escape_formula(item.get("display_name", "")), "", "", escape_formula(label)]
        if include_email:
            row.insert(1, escape_formula(ticket.booking.original_email if ticket else ""))
        writer.writerow(row)
    del unassigned
    return buffer.getvalue()
