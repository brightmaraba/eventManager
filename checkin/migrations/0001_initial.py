# Generated by Django 4.1 on 2024-11-28 18:02

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Ticket",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("payment_id", models.CharField(max_length=255, unique=True)),
                ("checked_in", models.BooleanField(default=False)),
            ],
        ),
    ]
