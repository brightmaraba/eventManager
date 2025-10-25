# tickets/management/commands/email_ticket_pdfs.py

import os
from django.core.management.base import BaseCommand
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from weasyprint import HTML, CSS
from tickets.models import Ticket
from django.template.loader import render_to_string

class Command(BaseCommand):
    help = 'Generate PDFs for tickets and email them to users'

    def add_arguments(self, parser):
        parser.add_argument(
            '--ticket-id',
            type=int,
            help='Email PDF for a specific ticket ID',
        )

    def handle(self, *args, **options):
        ticket_id = options.get('ticket_id')
        email_count = 0  # Initialize email counter

        if ticket_id:
            tickets = Ticket.objects.filter(id=ticket_id)
            if not tickets.exists():
                self.stdout.write(self.style.ERROR(f"No ticket found with ID {ticket_id}"))
                return
        else:
            # Filter tickets that have not been been generated and emailed
            tickets = Ticket.objects.filter(ticket_generated=True, email_sent=False)

        for ticket in tickets:
            # Generate PDF
            file_path = os.path.join(settings.MEDIA_ROOT, 'tickets', f'ticket_{ticket.id}.pdf')
            context = {'ticket': ticket}
            html_string = render_to_string('ticket.html', context)

            # Convert static and media URLs to absolute paths
            html_string = html_string.replace(
                '{% static ', f'file://{os.path.join(settings.STATIC_ROOT, "")}'
            )
            html_string = html_string.replace(
                '/media/', f'file://{settings.MEDIA_ROOT}/'
            )

            pdf_file = HTML(string=html_string).write_pdf(stylesheets=[CSS(string='@page { size: A4; margin: 1cm; }')])

            with open(file_path, 'wb') as f:
                f.write(pdf_file)

            # Prepare email
            email_subject = 'Your Kalenjin Gala Night Ticket'
            email_body = render_to_string('tickets_email.html', context)
            email = EmailMultiAlternatives(
                subject=email_subject,
                body=email_body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[ticket.email],
            )
            email.attach_alternative(email_body, "text/html")
            email.attach_file(file_path)

            # Send email
            email.send()
            email_count += 1  # Increment email counter

            self.stdout.write(self.style.SUCCESS(f"Email sent to {ticket.email} with attached PDF: {file_path}"))
            # Update ticket to indicate it has been emailed
            ticket.email_sent = True
            ticket.ticket_generated = True
            ticket.save()

        self.stdout.write(self.style.SUCCESS(f"All emails sent successfully. Total emails sent: {email_count}"))