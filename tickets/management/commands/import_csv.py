import csv
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from tickets.models import Ticket
from dateutil import parser


class Command(BaseCommand):
    help = "Import tickets from a CSV file"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Simulate the import without creating or modifying tickets",
        )

    def handle(self, *args, **options):
        file_path = Path(settings.BASE_DIR) / "tickets.csv"

        dry_run = options.get("dry_run", False)
        created_count = 0
        existing_count = 0

        with open(file_path, mode="r", encoding="utf-8") as file:
            reader = csv.DictReader(file)
            for row in reader:
                if dry_run:
                    if Ticket.objects.filter(payment_id=row["id"]).exists():
                        existing_count += 1
                        self.stdout.write(
                            self.style.WARNING(
                                f"[DRY RUN] Ticket {row['id']} already exists"
                            )
                        )
                    else:
                        created_count += 1
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"[DRY RUN] Would add ticket {row['id']}"
                            )
                        )
                else:
                    ticket, created = Ticket.objects.get_or_create(
                        payment_id=row["id"],
                        defaults={
                            "email": row["Customer Email"],
                            "date": parser.parse(row["Created date (UTC)"]),
                            "amount_paid": float(row["Amount"]),
                        },
                    )
                    if created:
                        created_count += 1
                        self.stdout.write(
                            self.style.SUCCESS(f"Added ticket {ticket.payment_id}")
                        )
                    else:
                        existing_count += 1
                        self.stdout.write(
                            self.style.WARNING(
                                f"Ticket {ticket.payment_id} already exists"
                            )
                        )

        if dry_run:
            self.stdout.write(
                self.style.SUCCESS(
                    f"DRY RUN COMPLETE: {created_count} tickets would be created, "
                    f"{existing_count} tickets already exist."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Tickets import process completed! "
                    f"Created {created_count} tickets, {existing_count} already existed."
                )
            )
