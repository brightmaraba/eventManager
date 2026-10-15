from django.conf import settings
from django.core.cache import cache

from accounts.models import EventGrant, Membership
from core.errors import Throttled


def membership_for(user, organization):
    if not user.is_authenticated:
        return None
    return Membership.objects.filter(user=user, organization=organization).first()


def grant_for(user, event):
    if not user.is_authenticated:
        return None
    return EventGrant.objects.filter(user=user, event=event).first()


def mfa_required(user):
    if settings.DEBUG or not getattr(user, "is_authenticated", False):
        return False
    if user.is_platform_admin or user.is_superuser:
        return True
    return Membership.objects.filter(
        user=user,
        role__in=[Membership.Role.OWNER, Membership.Role.EVENT_ADMINISTRATOR],
    ).exists()


def can_view(user, event):
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_platform_admin:
        return True
    if membership_for(user, event.organization):
        return True
    return grant_for(user, event) is not None


def can_manage_members(user, organization):
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_platform_admin:
        return True
    membership = membership_for(user, organization)
    return bool(membership and membership.role == Membership.Role.OWNER)


def can_manage_event(user, event):
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_platform_admin:
        return True
    membership = membership_for(user, event.organization)
    return bool(
        membership and membership.role in {Membership.Role.OWNER, Membership.Role.EVENT_ADMINISTRATOR}
    )


def can_edit_layout(user, event):
    if can_manage_event(user, event):
        return True
    grant = grant_for(user, event)
    return bool(grant and grant.role == EventGrant.Role.SEATING_COORDINATOR)


def can_import(user, event):
    return can_manage_event(user, event)


def can_publish(user, event):
    return can_manage_event(user, event)


def can_communicate(user, event):
    return can_manage_event(user, event)


def can_checkin(user, event):
    if can_manage_event(user, event):
        return True
    grant = grant_for(user, event)
    return bool(grant and grant.role == EventGrant.Role.CHECKIN_STAFF)


def can_export(user, event):
    if can_manage_event(user, event):
        return True
    grant = grant_for(user, event)
    return bool(grant and grant.can_export and grant.role != EventGrant.Role.CHECKIN_STAFF)


def can_view_accessibility(user, event):
    return can_manage_event(user, event)


def throttle(bucket, limit, period):
    key = f"throttle:{bucket}"
    try:
        if cache.add(key, 1, period):
            return
        count = cache.incr(key)
    except Exception:
        return
    if count > limit:
        raise Throttled()
