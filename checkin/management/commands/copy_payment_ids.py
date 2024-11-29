# checkin/management/commands/copy_payment_ids.py

from django.core.management.base import BaseCommand
from tickets.models import Ticket  # Import Ticket from the tickets app
from checkin.models import Ticket as CheckInTicket

class Command(BaseCommand):
    help = 'Copy payment_id from Ticket to CheckIn, skipping existing ones.'

    def handle(self, *args, **kwargs):
        # Get all payment_ids from Ticket
        ticket_payment_ids = Ticket.objects.values_list('payment_id', flat=True)

        # Get existing payment_ids in CheckIn
        existing_payment_ids = set(CheckInTicket.objects.values_list('payment_id', flat=True))

        # Filter out existing payment_ids
        new_payment_ids = [pid for pid in ticket_payment_ids if pid not in existing_payment_ids]

        # Create new CheckIn entries
        checkins_to_create = [CheckInTicket(payment_id=pid) for pid in new_payment_ids]
        CheckInTicket.objects.bulk_create(checkins_to_create)

        self.stdout.write(self.style.SUCCESS(f'Successfully copied {len(checkins_to_create)} payment_ids.'))