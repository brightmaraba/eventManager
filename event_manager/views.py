# tickets/views.py

from django.shortcuts import render
from django.core.paginator import Paginator
from tickets.models import Ticket

def home(request):
    # Retrieve all tickets
    tickets = Ticket.objects.all()

    # Set up pagination with 50 tickets per page
    paginator = Paginator(tickets, 25)  # Show 50 tickets per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Pass the page object to the template context
    context = {
        'page_obj': page_obj,
    }

    return render(request, 'home.html', context)