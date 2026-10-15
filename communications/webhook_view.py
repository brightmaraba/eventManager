import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from communications.webhooks import apply_events, verify_signature
from core.http import error_response
from core.errors import DomainError


@csrf_exempt
@require_POST
def sendgrid_events(request):
    try:
        verify_signature(
            request.body,
            request.headers.get("X-Twilio-Email-Event-Webhook-Signature", ""),
            request.headers.get("X-Twilio-Email-Event-Webhook-Timestamp", ""),
        )
        payload = json.loads(request.body.decode() or "[]")
        if isinstance(payload, dict):
            payload = [payload]
        effects = apply_events(payload)
    except DomainError as exc:
        return error_response(request, exc)
    except json.JSONDecodeError:
        return JsonResponse({"code": "invalid_payload", "message": "Malformed JSON."}, status=400)
    return JsonResponse({"ok": True, "effects": effects})
