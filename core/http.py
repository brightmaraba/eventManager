from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from accounts.permissions import mfa_required
from core.errors import DomainError


def wants_json(request):
    if request.content_type == "application/json":
        return True
    accept = request.headers.get("Accept", "")
    return "application/json" in accept and "text/html" not in accept


def error_payload(request, exc):
    payload = {
        "code": exc.code,
        "message": exc.message,
        "field_errors": exc.field_errors,
        "current_revision": exc.revision,
        "request_id": getattr(request, "request_id", ""),
    }
    payload.update(exc.extra)
    return payload


def error_response(request, exc):
    payload = error_payload(request, exc)
    if wants_json(request):
        return JsonResponse(payload, status=exc.status)
    return render(request, "error.html", {"error": exc, "payload": payload}, status=exc.status)


def json_result(result):
    response = JsonResponse(result.body, status=result.status)
    if result.replayed:
        response["Idempotency-Replayed"] = "true"
    return response


def require_login(view):
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"{reverse('login')}?next={request.get_full_path()}")
        if mfa_required(request.user) and not request.user.is_verified():
            return redirect("mfa-verify")
        try:
            return view(request, *args, **kwargs)
        except DomainError as exc:
            return error_response(request, exc)

    return wrapper
