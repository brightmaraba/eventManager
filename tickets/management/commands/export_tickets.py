import csv
import json
import os
from datetime import datetime
from django.core.management.base import BaseCommand
from django.utils import timezone
from tickets.models import Ticket


class Command(BaseCommand):
    help = "Export all ticket data from the database to CSV or JSON format"

    def add_arguments(self, parser):
        parser.add_argument(
            "--format",
            type=str,
            choices=["csv", "json"],
            default="csv",
            help="Output format: csv or json (default: csv)",
        )
        parser.add_argument(
            "--output",
            type=str,
            help="Output file path (optional, defaults to tickets_export_TIMESTAMP.csv/json)",
        )

    def handle(self, *args, **options):
        format_type = options["format"]
        output_path = options.get("output")

        # Get all tickets
        tickets = Ticket.objects.all().order_by("-date")

        if not tickets.exists():
            self.stdout.write(self.style.WARNING("No tickets found in the database."))
            return

        # Generate default output path if not provided
        if not output_path:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = f"tickets_export_{timestamp}.{format_type}"

        # Export based on format
        if format_type == "csv":
            self.export_csv(tickets, output_path)
        elif format_type == "json":
            self.export_json(tickets, output_path)

        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully exported {tickets.count()} tickets to {output_path}"
            )
        )

    def export_csv(self, tickets, output_path):
        """Export tickets to CSV format"""
        fieldnames = [
            "id",
            "ticket_number",
            "payment_id",
            "email",
            "date",
            "amount_paid",
            "checked_in",
            "ticket_generated",
            "email_sent",
            "qr_code",
            "logo",
            "banner",
        ]

        with open(output_path, "w", newline="", encoding="utf-8") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            for ticket in tickets:
                writer.writerow(
                    {
                        "id": ticket.id,
                        "ticket_number": ticket.ticket_number or "",
                        "payment_id": ticket.payment_id,
                        "email": ticket.email,
                        "date": ticket.date.isoformat() if ticket.date else "",
                        "amount_paid": str(ticket.amount_paid),
                        "checked_in": ticket.checked_in,
                        "ticket_generated": ticket.ticket_generated,
                        "email_sent": ticket.email_sent,
                        "qr_code": ticket.qr_code.url if ticket.qr_code else "",
                        "logo": ticket.logo.url if ticket.logo else "",
                        "banner": ticket.banner.url if ticket.banner else "",
                    }
                )

    def export_json(self, tickets, output_path):
        """Export tickets to JSON format"""
        data = []
        for ticket in tickets:
            data.append(
                {
                    "id": ticket.id,
                    "ticket_number": ticket.ticket_number,
                    "payment_id": ticket.payment_id,
                    "email": ticket.email,
                    "date": ticket.date.isoformat() if ticket.date else None,
                    "amount_paid": str(ticket.amount_paid),
                    "checked_in": ticket.checked_in,
                    "ticket_generated": ticket.ticket_generated,
                    "email_sent": ticket.email_sent,
                    "qr_code": ticket.qr_code.url if ticket.qr_code else None,
                    "logo": ticket.logo.url if ticket.logo else None,
                    "banner": ticket.banner.url if ticket.banner else None,
                }
            )

        with open(output_path, "w", encoding="utf-8") as jsonfile:
            json.dump(data, jsonfile, indent=2, ensure_ascii=False)
