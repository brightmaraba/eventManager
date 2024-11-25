from django.contrib import admin
from .models import Ticket

@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ('payment_id', 'ticket_number', 'email', 'checked_in', 'date', 'amount_paid')
    list_filter = ('checked_in',)
