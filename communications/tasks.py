from celery import shared_task


@shared_task(name="communications.dispatch_due_mail")
def dispatch_due_mail():
    from communications.services import dispatch_pending

    dispatch_pending()


@shared_task(name="communications.reconcile_abandoned_claims")
def reconcile_abandoned_claims_task():
    from communications.recovery import reconcile_abandoned_claims

    reconcile_abandoned_claims()
