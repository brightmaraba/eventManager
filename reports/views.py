from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from accounts.permissions import can_export, can_view
from core.errors import NotFound
from core.http import require_login
from events.views import load_event
from reports.models import ExportJob
from reports.services import assignments_csv, queue_pdf, render_html, render_job


@require_login
@require_http_methods(["GET"])
def print_view(request, event_id, kind):
    event = load_event(request, event_id, can_view)
    public = request.GET.get("public", "yes") != "no"
    if not public and not can_export(request.user, event):
        from core.errors import Denied
        raise Denied()
    html = render_html(
        event, kind, public_variant=public, paper=request.GET.get("paper", "a4"),
        orientation=request.GET.get("orientation", "landscape"), fit_mode=request.GET.get("fit", "fit"),
        publication_id=request.GET.get("publication") or None,
    )
    return HttpResponse(html)


@require_login
@require_http_methods(["GET", "POST"])
def exports(request, event_id):
    event = load_event(request, event_id, can_view)
    if request.method == "POST":
        if request.POST.get("format") == "csv":
            csv_text = assignments_csv(event, include_email=request.POST.get("include_email") == "yes", actor=request.user)
            response = HttpResponse(csv_text, content_type="text/csv")
            response["Content-Disposition"] = 'attachment; filename="assignments.csv"'
            return response
        job = queue_pdf(
            event=event, actor=request.user, request_id=request.request_id, kind=request.POST.get("kind", "room_plan"),
            public_variant=request.POST.get("public", "yes") != "no", paper=request.POST.get("paper", "a4"),
            orientation=request.POST.get("orientation", "landscape"), fit_mode=request.POST.get("fit", "fit"),
        )
        render_job(job.id)
        return redirect("export-detail", event_id=event.id, job_id=job.id)
    return render(request, "reports/exports.html", {"event": event, "jobs": event.exports.all()[:20]})


@require_login
@require_http_methods(["GET"])
def export_detail(request, event_id, job_id):
    event = load_event(request, event_id, can_view)
    job = ExportJob.objects.filter(pk=job_id, event=event).first()
    if job is None or job.requester_id != request.user.id and not can_export(request.user, event):
        raise NotFound()
    if request.GET.get("download") and job.artifact and job.expires_at and job.state == ExportJob.State.READY:
        from django.utils import timezone
        if job.expires_at <= timezone.now():
            raise NotFound()
        return FileResponse(job.artifact.open("rb"), as_attachment=True, filename=f"{job.kind}.pdf")
    return render(request, "reports/export_detail.html", {"event": event, "job": job})
