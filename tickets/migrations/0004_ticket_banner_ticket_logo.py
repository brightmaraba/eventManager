# Generated by Django 5.1.3 on 2024-11-24 23:19

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tickets', '0003_alter_ticket_options_ticket_qr_code_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='ticket',
            name='banner',
            field=models.ImageField(blank=True, default='default/banner.jpg', null=True, upload_to='banners/'),
        ),
        migrations.AddField(
            model_name='ticket',
            name='logo',
            field=models.ImageField(blank=True, default='default/logo.png', null=True, upload_to='logos/'),
        ),
    ]