from celery import shared_task


@shared_task(name="seating.expire_holds")
def expire_holds():
    from django.db import transaction
    from django.utils import timezone

    from core.locking import lock_event
    from seating.models import Hold
    from seating.services import release_expired

    event_ids = (
        Hold.objects.filter(released_at__isnull=True, expires_at__isnull=False, expires_at__lte=timezone.now())
        .values_list("event_id", flat=True)
        .distinct()
    )
    for event_id in event_ids:
        with transaction.atomic():
            event = lock_event(event_id)
            release_expired(event, actor=None, request_id="beat")
