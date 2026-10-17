import os

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand

from core.dbroles import admin_dsn_from_env, provision


def read_secret(name):
    path = os.getenv(f"{name}_FILE")
    if path:
        return open(path, encoding="utf-8").read().strip()
    return os.getenv(name, "")


class Command(BaseCommand):
    help = "Create least-privilege database roles, migrate, and collect static files."

    def handle(self, *args, **options):
        database = settings.DATABASES["default"]["NAME"]
        dsn = admin_dsn_from_env(database)
        if dsn:
            migrate_password = read_secret("POSTGRES_PASSWORD")
            runtime_password = read_secret("POSTGRES_RUNTIME_PASSWORD")
            if not migrate_password or not runtime_password:
                raise SystemExit("Migration and runtime database passwords are required for provisioning.")
            provision(
                dsn,
                database=database,
                migrate_role=os.getenv("POSTGRES_USER", "event_tables_migrate"),
                migrate_password=migrate_password,
                app_role=os.getenv("POSTGRES_APP_USER", "event_tables_app"),
                app_password=runtime_password,
            )
        call_command("migrate", interactive=False)
        call_command("collectstatic", interactive=False, verbosity=0)
        if os.getenv("ADMIN_EMAIL"):
            call_command("ensure_admin")
