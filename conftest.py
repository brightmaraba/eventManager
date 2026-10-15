import pytest


@pytest.fixture(autouse=True)
def fast_passwords(settings):
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


@pytest.fixture
def owner(db):
    from accounts.models import Membership, Organization, User

    user = User.objects.create_user("owner@example.test", "S3cure-pass-word")
    organization = Organization.objects.create(name="North Hall", slug="north-hall")
    Membership.objects.create(user=user, organization=organization, role=Membership.Role.OWNER)
    return user, organization


@pytest.fixture
def event(owner):
    from events.services import create_event

    user, organization = owner
    return create_event(
        actor=user,
        organization=organization,
        data={
            "name": "Spring dinner",
            "venue_name": "North Hall",
            "address_line1": "1 Example Street",
            "locality": "Nairobi",
            "postal_code": "00100",
            "country": "Kenya",
            "timezone": "Africa/Nairobi",
            "starts_at": "2026-11-20T18:00",
            "ends_at": "2026-11-20T22:00",
            "doors_open_at": "2026-11-20T17:30",
            "initial_table_count": 10,
            "default_seats_per_table": 8,
        },
        request_id="test",
    )
