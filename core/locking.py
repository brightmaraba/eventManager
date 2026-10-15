from django.db import transaction


def lock_event(event_id):
    from events.models import Event

    return Event.objects.select_for_update().get(pk=event_id)


def locked(queryset):
    return list(queryset.order_by("pk").select_for_update())


def atomic(fn):
    def wrapper(*args, **kwargs):
        with transaction.atomic():
            return fn(*args, **kwargs)

    return wrapper
