import pytest
from django.core import mail

from communications.models import EmailDelivery
from communications.provider import AmbiguousSMTP
from communications.services import create_campaign, dispatch_pending, queue_campaign
from guests.services import get_or_create_booking, set_quantity


@pytest.fixture
def booking(owner, event):
    user, _organization = owner
    created, _unused = get_or_create_booking(event=event, email="guest@example.test", party_name="Guest")
    set_quantity(event=event, booking=created, target=1, actor=user, request_id="test")
    return created


@pytest.mark.django_db
def test_mail_is_submitted_once_and_not_marked_delivered(owner, event, booking, settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    user, _organization = owner
    campaign = create_campaign(event=event, actor=user, kind="invitation", subject="Join us", audience_filter={"kind": "all"}, request_id="test")
    queue_campaign(campaign=campaign, actor=user, request_id="test")
    dispatch_pending()
    delivery = EmailDelivery.objects.get()
    assert delivery.state == "submitted"
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["guest@example.test"]
    dispatch_pending()
    assert len(mail.outbox) == 1


@pytest.mark.django_db
def test_ambiguous_send_is_not_retried(owner, event, booking, settings, monkeypatch):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    user, _organization = owner
    campaign = create_campaign(event=event, actor=user, kind="invitation", subject="Join us", audience_filter={"kind": "all"}, request_id="test")
    queue_campaign(campaign=campaign, actor=user, request_id="test")

    def explode(_delivery):
        raise AmbiguousSMTP("connection dropped")

    monkeypatch.setattr("communications.services.deliver", explode)
    dispatch_pending()
    delivery = EmailDelivery.objects.get()
    assert delivery.state == "ambiguous"
    dispatch_pending()
    assert EmailDelivery.objects.get().state == "ambiguous"
    assert mail.outbox == []


@pytest.mark.django_db
def test_pending_row_survives_until_dispatch(owner, event, booking, settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    user, _organization = owner
    campaign = create_campaign(event=event, actor=user, kind="reminder", subject="Reminder", audience_filter={"kind": "all"}, request_id="test")
    queue_campaign(campaign=campaign, actor=user, request_id="test")
    assert EmailDelivery.objects.filter(state="pending").count() == 1
    dispatch_pending()
    assert EmailDelivery.objects.filter(state="submitted").count() == 1
