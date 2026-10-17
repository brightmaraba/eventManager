from django.contrib import admin
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import include, path
from django.conf import settings
from redis import Redis

from checkin.views import scan_code
from communications.webhook_view import sendgrid_events
from core.metrics import metrics
from guests.public import guest_seating


def live(request):
    return JsonResponse({"status": "ok"})


def ready(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        Redis.from_url(settings.CELERY_BROKER_URL, socket_connect_timeout=2, socket_timeout=2).ping()
    except Exception:
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ready"})


def home(request):
    if request.user.is_authenticated:
        from checkin.dashboard import landing_path

        return redirect(landing_path(request.user))
    return redirect("login")


urlpatterns = [
    path("", home, name="home"),
    path("accounts/", include("accounts.urls")),
    path("events/", include("events.urls")),
    path("guest/<str:token>/", guest_seating, name="guest-seating"),
    path("checkin/t/<str:token>/", scan_code, name="checkin-scan"),
    path("integrations/sendgrid/events/", sendgrid_events, name="sendgrid-events"),
    path("ops/metrics/", metrics, name="metrics"),
    path("admin/", admin.site.urls),
    path("health/live/", live, name="health-live"),
    path("health/ready/", ready, name="health-ready"),
]
