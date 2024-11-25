from django.shortcuts import render, get_object_or_404
from .models import Ticket

def ticket_view(request, payment_id):
    ticket = get_object_or_404(Ticket, payment_id=payment_id)
    return render(request, 'ticket.html', {'ticket': ticket})

def check_in(request, payment_id):
    ticket = get_object_or_404(Ticket, payment_id=payment_id)
    ticket.checked_in = True
    ticket.save()
    return redirect('success_page')  # Redirect to a success page