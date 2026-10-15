from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import Membership, Organization, User
from events.services import create_event
from layouts.workload import build_reference_workload


class Command(BaseCommand):
    help = "Create the 1000-table, 10000-ticket reference event. Development only."

    def handle(self, *args, **options):
        from django.conf import settings

        if not settings.DEBUG:
            raise SystemExit("load_ui_fixture runs only when DJANGO_DEBUG=1.")
        with transaction.atomic():
            user, _created = User.objects.get_or_create(
                email="owner@example.test",
                defaults={"is_platform_admin": True, "is_staff": True},
            )
            organization, _org_created = Organization.objects.get_or_create(
                slug="north-hall",
                defaults={"name": "North Hall"},
            )
            Membership.objects.get_or_create(
                user=user,
                organization=organization,
                defaults={"role": Membership.Role.OWNER},
            )
            if organization.events.filter(slug="reference-hall").exists():
                self.stdout.write("Reference hall already exists.")
                return
            event = create_event(
                actor=user,
                organization=organization,
                data={
                    "name": "Reference hall",
                    "venue_name": "North Hall",
                    "address_line1": "1 Example Street",
                    "locality": "Nairobi",
                    "postal_code": "00100",
                    "country": "Kenya",
                    "timezone": "Africa/Nairobi",
                    "starts_at": "2026-11-20T18:00",
                    "ends_at": "2026-11-20T22:00",
                    "doors_open_at": "2026-11-20T17:30",
                    "initial_table_count": 0,
                    "default_seats_per_table": 10,
                },
                request_id="ui-fixture",
            )
            counts = build_reference_workload(event)
        self.stdout.write(f"Reference hall: {counts['tables']} tables, {counts['tickets']} tickets.")
