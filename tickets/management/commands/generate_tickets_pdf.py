# tickets/management/commands/generate_ticket_pdfs.py

from django.core.management.base import BaseCommand
from django.template.loader import render_to_string
from django.conf import settings
from xhtml2pdf import pisa
from tickets.models import Ticket
import os

class Command(BaseCommand):
    help = 'Generate PDF versions of tickets and save to media/pdfs'

    def handle(self, *args, **kwargs):
        tickets = Ticket.objects.all()
        pdf_dir = os.path.join(settings.MEDIA_ROOT, 'pdfs')
        os.makedirs(pdf_dir, exist_ok=True)

        for ticket in tickets:
            # Render HTML content
            html_content = render_to_string('ticket.html', {'ticket': ticket})

            # Convert static and media URLs to absolute paths
            html_content = html_content.replace(
                '/static/', f'file://{os.path.join(settings.BASE_DIR, "static")}/'
            )
            html_content = html_content.replace(
                '/media/', f'file://{settings.MEDIA_ROOT}/'
            )

            # Define PDF path
            pdf_path = os.path.join(pdf_dir, f'ticket_{ticket.ticket_number}.pdf')

            # Generate PDF
            with open(pdf_path, 'wb') as pdf_file:
                pisa_status = pisa.CreatePDF(html_content, dest=pdf_file)

            if pisa_status.err:
                self.stdout.write(self.style.ERROR(f'Error generating PDF for {ticket.email}'))
            else:
                self.stdout.write(self.style.SUCCESS(f'Successfully generated PDF for {ticket.email}'))