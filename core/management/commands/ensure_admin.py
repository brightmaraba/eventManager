import os

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand

from accounts.models import User
from core.management.commands.release_prepare import read_secret


class Command(BaseCommand):
    help = "Create or update the platform administrator from ADMIN_EMAIL and ADMIN_PASSWORD."

    def handle(self, *args, **options):
        email = os.getenv("ADMIN_EMAIL", "").strip()
        password = read_secret("ADMIN_PASSWORD")
        if not email or not password:
            raise SystemExit("ADMIN_EMAIL and ADMIN_PASSWORD are required.")
        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            user = User(email=User.objects.normalize_email(email))
        user.is_active = True
        user.is_staff = True
        user.is_superuser = True
        user.is_platform_admin = True
        try:
            validate_password(password, user)
        except ValidationError as error:
            raise SystemExit(" ".join(error.messages)) from error
        user.set_password(password)
        user.save()
        self.stdout.write(f"Platform administrator ready: {user.email}")
