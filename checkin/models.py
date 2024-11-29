from django.db import models

class Ticket(models.Model):
    payment_id = models.CharField(max_length=255, unique=True)
    checked_in = models.BooleanField(default=False)

    def __str__(self):
        return self.payment_id