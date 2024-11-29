from django.shortcuts import render, get_object_or_404
from .models import Ticket

def check_in(request, payment_id):
    ticket = get_object_or_404(Ticket, payment_id=payment_id)
    if ticket.checked_in:
        return render(request, 'checkin/already_checked_in.html', {'ticket': ticket})
    else:
        ticket.checked_in = True
        ticket.save()
        return render(request, 'checkin/check_in_success.html', {'ticket': ticket})