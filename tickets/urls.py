from django.urls import path
from . import views

urlpatterns = [
    path('ticket/<str:payment_id>/', views.ticket_view, name='ticket_view'),
    path('check_in/', views.check_in, name='check_in'),
]