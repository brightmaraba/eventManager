from datetime import timedelta

from celery import shared_task
from django.utils import timezone


@shared_task(name="core.retention_cleanup")
def retention_cleanup():
    from events.models import Event
    from guests.models import ImportBatch
    from reports.models import ExportJob

    now = timezone.now()
    for batch in ImportBatch.objects.filter(created_at__lt=now - timedelta(days=1)).select_related("event__organization"):
        days = batch.event.organization.retention_import_days
        if batch.created_at < now - timedelta(days=days) and batch.source:
            batch.source.delete(save=True)
    for job in ExportJob.objects.filter(expires_at__lt=now):
        if job.artifact:
            job.artifact.delete(save=False)
        job.state = ExportJob.State.FAILED
        job.error = "expired"
        job.save(update_fields=["artifact", "state", "error"])
    for event in Event.objects.filter(retention_date__lt=now.date(), personal_data_purged_at__isnull=True, status__in=["completed", "archived", "cancelled"]):
        from events.services import purge_personal_data

        purge_personal_data(actor=None, event=event, reason="retention", request_id="beat")
