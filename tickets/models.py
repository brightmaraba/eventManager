# tickets/models.py
import qrcode
from io import BytesIO
from django.core.files import File
from django.db import models

class Ticket(models.Model):
    id = models.AutoField(primary_key=True)
    ticket_number = models.PositiveIntegerField(unique=True, null=True, blank=True)
    payment_id = models.CharField(max_length=50, unique=True)
    email = models.EmailField()
    date = models.DateTimeField(auto_now_add=True)
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2)
    checked_in = models.BooleanField(default=False)
    ticket_generated = models.BooleanField(default=True)
    email_sent = models.BooleanField(default=False)
    qr_code = models.ImageField(upload_to='qr_codes/', blank=True, null=True)
    logo = models.ImageField(upload_to='logos/', default='default/logo.jpg', blank=True, null=True)
    banner = models.ImageField(upload_to='banners/', default='default/banner.jpg', blank=True, null=True)

    def save(self, *args, **kwargs):
        if not self.ticket_number:
            last_ticket = Ticket.objects.order_by('-ticket_number').first()
            self.ticket_number = (last_ticket.ticket_number + 1) if last_ticket else 1

        # Generate QR code
        qr = qrcode.make(f"https://brightkoech.pythonanywhere.com/check_in/{self.payment_id}")
        qr_io = BytesIO()
        qr.save(qr_io, format='PNG')
        qr_io.seek(0)  # Reset the stream position to the beginning

        # Save the QR code image to the qr_code field
        self.qr_code.save(f'qr_{self.ticket_number}.png', File(qr_io), save=False)

        super().save(*args, **kwargs)

    def __str__(self):
        return f"Ticket {self.ticket_number} - {self.payment_id}"

    class Meta:
        ordering = ['-date']
        verbose_name = 'Ticket'
        verbose_name_plural = 'Tickets'