import pytest
from django.core.management import call_command

from accounts.models import User


@pytest.mark.django_db
def test_ensure_admin_creates_platform_administrator(monkeypatch, tmp_path):
    secret = tmp_path / "admin_password.txt"
    secret.write_text("Distinct-admin-pass-99\n", encoding="utf-8")
    monkeypatch.setenv("ADMIN_EMAIL", "brightkoech@libranconsult.tech")
    monkeypatch.setenv("ADMIN_PASSWORD_FILE", str(secret))

    call_command("ensure_admin")

    user = User.objects.get(email="brightkoech@libranconsult.tech")
    assert user.is_active
    assert user.is_staff
    assert user.is_superuser
    assert user.is_platform_admin
    assert user.check_password("Distinct-admin-pass-99")
