from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from accounts.models import User
from core.errors import DomainError
from guests.gala import (
    assign_parties,
    ensure_gala_event,
    ensure_ticket_campaign,
    import_payments,
    place_tables,
    publish_gala,
    read_payments,
    send_ticket_campaign,
)


class Command(BaseCommand):
    help = "Load the Kalenjin Association Gala 2026 roster, tables, and ticket campaign."

    def add_arguments(self, parser):
        parser.add_argument("--csv", default="")
        parser.add_argument("--send", action="store_true", help="Send ticket emails when SMTP is configured.")

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("load_gala runs only when DJANGO_DEBUG=1.")
        actor = User.objects.filter(email="owner@example.test").first()
        if actor is None:
            raise CommandError("Create the dev owner with seed_demo before loading the gala.")
        path = options["csv"] or str(settings.BASE_DIR / "unified_payments_with_ids.csv")
        try:
            rows = read_payments(path)
            event = ensure_gala_event(actor)
            imported = import_payments(event, actor, rows, "load-gala")
            place_tables(event, actor, "load-gala")
            assign_parties(event, actor, rows, "load-gala")
            publication = publish_gala(event, actor, "load-gala")
            campaign = ensure_ticket_campaign(event, actor, "load-gala")
            if options["send"]:
                send_ticket_campaign(event, actor, "load-gala")
        except DomainError as exc:
            raise CommandError(exc.message) from exc
        event.refresh_from_db()
        self.stdout.write(
            f"Gala {event.slug}: tickets created {imported['created']}, publication {publication.number}, campaign {campaign.status}."
        )
        if not options["send"]:
            self.stdout.write("Ticket emails were not sent. Pass --send after SMTP and PUBLIC_BASE_URL are set.")
