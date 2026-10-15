import json

from django.db import IntegrityError, transaction

from core.errors import Conflict
from core.models import IdempotencyRecord


class MutationResult:
    def __init__(self, body, status=200, replayed=False):
        self.body = body
        self.status = status
        self.replayed = replayed


def canonical(payload):
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def request_hash(payload):
    import hashlib

    return hashlib.sha256(canonical(payload).encode()).hexdigest()


def execute(*, organization, operation, key, payload, fn):
    digest = request_hash(payload)
    if not key:
        return MutationResult(fn())
    with transaction.atomic():
        existing = (
            IdempotencyRecord.objects.select_for_update()
            .filter(organization=organization, operation=operation, key=key)
            .first()
        )
        if existing:
            if existing.request_hash != digest:
                raise Conflict(
                    "idempotency_payload_mismatch",
                    "This idempotency key was already used for a different request.",
                )
            if not existing.completed:
                raise Conflict("idempotency_in_progress", "This request is still in progress.")
            return MutationResult(existing.response_body, existing.response_status, replayed=True)
        try:
            with transaction.atomic():
                record = IdempotencyRecord.objects.create(
                    organization=organization,
                    operation=operation,
                    key=key,
                    request_hash=digest,
                    completed=False,
                )
        except IntegrityError:
            record = IdempotencyRecord.objects.select_for_update().get(
                organization=organization, operation=operation, key=key
            )
            if record.request_hash != digest:
                raise Conflict(
                    "idempotency_payload_mismatch",
                    "This idempotency key was already used for a different request.",
                )
            return MutationResult(record.response_body, record.response_status, replayed=True)
        body = fn()
        record.response_body = body
        record.response_status = 200
        record.completed = True
        record.save(update_fields=["response_body", "response_status", "completed"])
        return MutationResult(body)
