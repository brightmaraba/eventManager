from django.shortcuts import render, get_object_or_404, redirect
from .models import Ticket
from django.http import HttpResponse

def ticket_view(request, payment_id):
    ticket = get_object_or_404(Ticket, payment_id=payment_id)
    return render(request, 'ticket.html', {'ticket': ticket})

def check_in(request, payment_id):
    ticket = get_object_or_404(Ticket, payment_id=payment_id)
    ticket.checked_in = True
    ticket.save()
    return redirect('success_page')  # Redirect to a success page

def check_in_ticket(request, payment_id):
    # Find the ticket by payment_id
    ticket = get_object_or_404(Ticket, payment_id=payment_id)

    # Update the checked_in field to True
    if not ticket.checked_in:
        ticket.checked_in = True
        ticket.save()
        return HttpResponse("Ticket checked in successfully.")
    else:
        return HttpResponse("Ticket has already been checked in.")