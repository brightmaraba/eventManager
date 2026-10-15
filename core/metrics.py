from django.contrib.auth.decorators import user_passes_test
from django.http import JsonResponse
from django.utils import timezone

from communications.models import EmailDelivery


@user_passes_test(lambda user: user.is_authenticated and user.is_platform_admin)
def metrics(request):
    pending = EmailDelivery.objects.filter(state=EmailDelivery.State.PENDING)
    oldest = pending.order_by("created_at").values_list("created_at", flat=True).first()
    age = None if oldest is None else int((timezone.now() - oldest).total_seconds())
    return JsonResponse({
        "pending_mail": pending.count(),
        "oldest_pending_seconds": age,
        "ambiguous_mail": EmailDelivery.objects.filter(state=EmailDelivery.State.AMBIGUOUS).count(),
        "failed_mail": EmailDelivery.objects.filter(state=EmailDelivery.State.FAILED).count(),
    })
