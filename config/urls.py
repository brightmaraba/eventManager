from django.contrib import admin
from django.db import connection
from django.http import JsonResponse
from django.urls import path
from django.conf import settings
from redis import Redis

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

urlpatterns = [path("admin/", admin.site.urls), path("health/live/", live), path("health/ready/", ready)]
