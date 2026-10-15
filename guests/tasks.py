from celery import shared_task


@shared_task(name="imports.health")
def import_health():
    return "ok"
