# tickets/admin.py

from django.contrib import admin
from .models import Ticket

@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ('payment_id', 'ticket_number', 'email', 'checked_in', 'date', 'amount_paid', 'ticket_generated', 'email_sent')
    list_filter = ('checked_in', 'ticket_generated', 'email_sent')
    search_fields = ('email',)  # Add search functionality for the email field
