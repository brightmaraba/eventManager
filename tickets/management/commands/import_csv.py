import csv
from django.core.management.base import BaseCommand
from tickets.models import Ticket
from dateutil import parser

class Command(BaseCommand):
    help = 'Import tickets from a CSV file'

    def handle(self, *args, **kwargs):
        file_path = '/home/brightkoech/eventManager/tickets/ticketsupdate.csv'

        with open(file_path, mode='r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            for row in reader:
                ticket, created = Ticket.objects.get_or_create(
                    payment_id=row['id'],
                    defaults={
                        'email': row['Customer Email'],
                        'date': parser.parse(row['Created date (UTC)']),
                        'amount_paid': float(row['Amount'])
                    }
                )
                if created:
                    self.stdout.write(self.style.SUCCESS(f'Added ticket {ticket.payment_id}'))
                else:
                    self.stdout.write(self.style.WARNING(f'Ticket {ticket.payment_id} already exists'))

        self.stdout.write(self.style.SUCCESS('Tickets import process completed!'))