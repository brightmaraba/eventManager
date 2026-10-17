import os
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from accounts.models import User
from core.errors import DomainError
from guests.gala import (
    assign_parties,
    ensure_gala_event,
    import_payments,
    place_tables,
    publish_gala,
    read_payments,
    send_ticket_campaign,
)


def gala_actor():
    email = os.getenv("ADMIN_EMAIL", "").strip()
    if email:
        actor = User.objects.filter(email__iexact=email).first()
        if actor is not None:
            return actor
    actor = User.objects.filter(is_platform_admin=True).order_by("date_joined").first()
    if actor is not None:
        return actor
    actor = User.objects.filter(email="owner@example.test").first()
    if actor is None:
        raise CommandError("Create the administrator before loading the gala.")
    return actor


class Command(BaseCommand):
    help = "Load the KACW GALA NIGHT roster for KACW NSW and send ticket emails."

    def add_arguments(self, parser):
        parser.add_argument("--csv", default="")
        parser.add_argument("--send", action="store_true", help="Send ticket emails. This is already the default.")
        parser.add_argument("--no-send", action="store_true", help="Load the roster without sending ticket emails.")

    def handle(self, *args, **options):
        actor = gala_actor()
        path = options["csv"] or str(settings.BASE_DIR / "unified_payments_with_ids.csv")
        if not Path(path).is_file():
            raise CommandError(f"Payment file not found: {path}")
        try:
            rows = read_payments(path)
            event = ensure_gala_event(actor)
            imported = import_payments(event, actor, rows, "load-gala")
            place_tables(event, actor, "load-gala")
            assign_parties(event, actor, rows, "load-gala")
            publication = publish_gala(event, actor, "load-gala")
        except DomainError as exc:
            raise CommandError(exc.message) from exc
        event.refresh_from_db()
        self.stdout.write(
            f"Gala {event.slug}: tickets created {imported['created']}, publication {publication.number}."
        )
        if options["no_send"]:
            self.stdout.write("Ticket emails were not sent.")
            return
        try:
            campaign = send_ticket_campaign(event, actor, "load-gala")
        except DomainError as exc:
            raise CommandError(exc.message) from exc
        from communications.models import EmailDelivery

        deliveries = EmailDelivery.objects.filter(audience__campaign=campaign)
        submitted = deliveries.filter(state__in=["submitted", "delivered"]).count()
        waiting = deliveries.filter(state__in=["pending", "claimed"]).count()
        self.stdout.write(f"Ticket emails submitted {submitted}, still waiting {waiting}.")
