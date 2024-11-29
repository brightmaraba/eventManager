from django.urls import path
from . import views

urlpatterns = [
    path('<str:payment_id>/', views.check_in, name='check_in'),
]