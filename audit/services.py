import hashlib


def redact_payload(value):
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            lowered = key.lower()
            if any(part in lowered for part in ("email", "token", "password", "secret", "notes")):
                redacted[key] = _mask(item)
            else:
                redacted[key] = redact_payload(item)
        return redacted
    if isinstance(value, list):
        return [redact_payload(item) for item in value]
    return value


def _mask(item):
    text = "" if item is None else str(item)
    if not text:
        return ""
    return "[redacted:" + hashlib.sha256(text.encode()).hexdigest()[:10] + "]"


def record(*, actor, organization, operation, object_type, object_id="", before=None, after=None, request_id="", reason="", event=None):
    from audit.models import AuditLog

    user = actor if getattr(actor, "is_authenticated", False) else actor if getattr(actor, "pk", None) else None
    return AuditLog.objects.create(
        organization=organization,
        event=event,
        actor=user,
        operation=operation,
        object_type=object_type,
        object_id=str(object_id or ""),
        reason=reason or "",
        before=redact_payload(before or {}),
        after=redact_payload(after or {}),
        request_id=request_id or "",
        roster_revision=getattr(event, "roster_revision", 0) or 0,
        layout_revision=getattr(event, "layout_revision", 0) or 0,
    )
