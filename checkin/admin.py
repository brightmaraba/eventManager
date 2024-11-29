from django.contrib import admin
from .models import Ticket

@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ('payment_id', 'checked_in')
    search_fields = ('payment_id',)