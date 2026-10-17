import base64
from io import BytesIO

import qrcode
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.views import PasswordResetCompleteView, PasswordResetConfirmView, PasswordResetDoneView, PasswordResetView
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods
from django_otp import login as otp_login
from django_otp.plugins.otp_totp.models import TOTPDevice

from accounts.models import EventGrant, Membership, Organization, User
from accounts.permissions import can_manage_members, mfa_required, throttle
from audit.services import record
from core.errors import Denied, DomainError
from core.http import require_login
from events.services import unique_slug


def _client_ip(request):
    return request.META.get("REMOTE_ADDR", "unknown")


@require_http_methods(["GET", "POST"])
def login_view(request):
    error = ""
    if request.method == "POST":
        throttle(f"login:{_client_ip(request)}", 10, 600)
        user = authenticate(request, username=request.POST.get("email", ""), password=request.POST.get("password", ""))
        if user is None or not user.is_active:
            error = "Those credentials were not accepted."
        elif mfa_required(user):
            request.session["mfa_user_pk"] = user.pk
            if not user.totpdevice_set.filter(confirmed=True).exists():
                return redirect("mfa-enroll")
            return redirect("mfa-verify")
        else:
            login(request, user)
            _select_default_org(request, user)
            from checkin.dashboard import landing_path

            destination = request.GET.get("next") or landing_path(user)
            if not destination.startswith("/") or destination.startswith("//"):
                destination = landing_path(user)
            return redirect(destination)
    return render(request, "accounts/login.html", {"error": error})


def _select_default_org(request, user):
    membership = user.memberships.select_related("organization").first()
    if membership:
        request.session["organization_id"] = str(membership.organization_id)


def _pending_user(request):
    pk = request.session.get("mfa_user_pk")
    return User.objects.filter(pk=pk, is_active=True).first() if pk else None


@require_http_methods(["GET", "POST"])
def mfa_enroll(request):
    user = _pending_user(request)
    if user is None:
        return redirect("login")
    device = user.totpdevice_set.filter(confirmed=False).first() or TOTPDevice.objects.create(user=user, name="authenticator", confirmed=False)
    if request.method == "POST":
        if device.verify_token(request.POST.get("token", "")):
            device.confirmed = True
            device.save(update_fields=["confirmed"])
            login(request, user)
            otp_login(request, device)
            request.session.pop("mfa_user_pk", None)
            _select_default_org(request, user)
            from checkin.dashboard import landing_path

            return redirect(landing_path(user))
        return render(request, "accounts/mfa.html", {"mode": "enroll", "error": "That code was not accepted.", "qr": _qr(device.config_url), "secret": device.key})
    return render(request, "accounts/mfa.html", {"mode": "enroll", "qr": _qr(device.config_url), "secret": device.key, "error": ""})


@require_http_methods(["GET", "POST"])
def mfa_verify(request):
    user = _pending_user(request)
    if user is None:
        return redirect("login")
    device = user.totpdevice_set.filter(confirmed=True).first()
    if device is None:
        return redirect("mfa-enroll")
    error = ""
    if request.method == "POST":
        throttle(f"mfa:{_client_ip(request)}", 10, 600)
        if device.verify_token(request.POST.get("token", "")):
            login(request, user)
            otp_login(request, device)
            request.session.pop("mfa_user_pk", None)
            _select_default_org(request, user)
            from checkin.dashboard import landing_path

            return redirect(landing_path(user))
        error = "That code was not accepted."
    return render(request, "accounts/mfa.html", {"mode": "verify", "error": error})


def _qr(data):
    image = qrcode.make(data)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()


@require_login
@require_http_methods(["POST"])
def logout_view(request):
    logout(request)
    return redirect("login")


@require_login
@require_http_methods(["GET", "POST"])
def organization_select(request):
    if request.method == "POST" and request.POST.get("organization_id"):
        organization = Organization.objects.filter(pk=request.POST["organization_id"]).first()
        if organization and (request.user.is_platform_admin or Membership.objects.filter(user=request.user, organization=organization).exists()):
            if request.user.is_platform_admin and not Membership.objects.filter(user=request.user, organization=organization).exists():
                record(actor=request.user, organization=organization, operation="platform_access", object_type="organization", object_id=organization.id, request_id=request.request_id)
            request.session["organization_id"] = str(organization.id)
            return redirect("event-list")
    if request.method == "POST" and request.POST.get("name"):
        if not request.user.is_platform_admin:
            raise Denied()
        organization = Organization.objects.create(name=request.POST["name"].strip(), slug=unique_slug(Organization, request.POST["name"]))
        record(actor=request.user, organization=organization, operation="organization_created", object_type="organization", object_id=organization.id, request_id=request.request_id, after={"name": organization.name})
        request.session["organization_id"] = str(organization.id)
        return redirect("members")
    organizations = Organization.objects.all() if request.user.is_platform_admin else Organization.objects.filter(memberships__user=request.user)
    return render(request, "accounts/organizations.html", {"organizations": organizations.distinct()})


@require_login
@require_http_methods(["GET", "POST"])
def members(request):
    organization = request.organization
    if organization is None:
        return redirect("organization-select")
    if not can_manage_members(request.user, organization):
        raise Denied()
    if request.method == "POST":
        email = request.POST.get("email", "").strip()
        role = request.POST.get("role")
        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            raise DomainError("unknown_user", "That person needs an account before they can be added.")
        Membership.objects.update_or_create(user=user, organization=organization, defaults={"role": role})
        record(actor=request.user, organization=organization, operation="membership_set", object_type="membership", object_id=user.id, request_id=request.request_id, after={"role": role})
        return redirect("members")
    return render(request, "accounts/members.html", {"memberships": organization.memberships.select_related("user"), "roles": Membership.Role.choices})


@require_login
@require_http_methods(["POST"])
def event_grant(request, event_id):
    from events.views import load_event
    from accounts.permissions import can_manage_event

    event = load_event(request, event_id, can_manage_event)
    email = request.POST.get("email", "").strip()
    user = User.objects.filter(email__iexact=email).first()
    if user is None:
        raise DomainError("unknown_user", "That person needs an account before they can be granted access.")
    if request.POST.get("remove") == "yes":
        EventGrant.objects.filter(user=user, event=event).delete()
    else:
        EventGrant.objects.update_or_create(
            user=user, event=event,
            defaults={"role": request.POST.get("role"), "can_export": request.POST.get("can_export") == "yes"},
        )
    record(actor=request.user, organization=event.organization, event=event, operation="event_grant_set", object_type="event_grant", object_id=user.id, request_id=request.request_id)
    return redirect("event-detail", event_id=event.id)
