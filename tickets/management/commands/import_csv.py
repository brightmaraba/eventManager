import csv
from django.core.management.base import BaseCommand
from tickets.models import Ticket
from datetime import datetime

class Command(BaseCommand):
    help = 'Import tickets from a CSV file'

    def handle(self, *args, **kwargs):
        with open('/home/brightkoech/eventManager/tickets/tickets.csv', mode='r') as file:
            reader = csv.DictReader(file)
            for row in reader:
                Ticket.objects.create(
                    payment_id=row['id'],
                    email=row['Customer Email'],
                    date=datetime.strptime(row['Created date (UTC)'], '%Y-%m-%d'),
                    amount_paid=row['Amount']
                )
        self.stdout.write(self.style.SUCCESS('Tickets imported successfully!'))
