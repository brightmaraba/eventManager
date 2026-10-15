from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import Membership, Organization, User
from events.services import create_event


class Command(BaseCommand):
    help = "Create a local demo organization, owner, and event. Development only."

    def handle(self, *args, **options):
        from django.conf import settings

        if not settings.DEBUG:
            raise SystemExit("seed_demo runs only when DJANGO_DEBUG=1.")
        with transaction.atomic():
            user, created = User.objects.get_or_create(email="owner@example.test", defaults={"is_platform_admin": True, "is_staff": True})
            if created or not user.check_password("S3cure-pass-word"):
                user.set_password("S3cure-pass-word")
                user.is_platform_admin = True
                user.is_staff = True
                user.save()
            organization, _ = Organization.objects.get_or_create(slug="north-hall", defaults={"name": "North Hall"})
            Membership.objects.get_or_create(user=user, organization=organization, defaults={"role": Membership.Role.OWNER})
            if not organization.events.filter(slug="spring-dinner").exists():
                create_event(
                    actor=user,
                    organization=organization,
                    data={
                        "name": "Spring dinner",
                        "slug": "spring-dinner",
                        "venue_name": "North Hall",
                        "address_line1": "1 Example Street",
                        "locality": "Nairobi",
                        "postal_code": "00100",
                        "country": "Kenya",
                        "timezone": "Africa/Nairobi",
                        "starts_at": "2026-11-20T18:00",
                        "ends_at": "2026-11-20T22:00",
                        "doors_open_at": "2026-11-20T17:30",
                        "initial_table_count": 2,
                        "default_seats_per_table": 8,
                    },
                    request_id="seed",
                )
        self.stdout.write("Demo owner: owner@example.test")
