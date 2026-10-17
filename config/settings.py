import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def secret(name, default=None):
    path = os.getenv(f"{name}_FILE")
    value = Path(path).read_text(encoding="utf-8").strip() if path else os.getenv(name, default)
    if not value:
        raise ImproperlyConfigured(f"Missing {name}")
    return value


DEBUG = os.getenv("DJANGO_DEBUG", "0") == "1"
SECRET_KEY = secret("DJANGO_SECRET_KEY")
ALLOWED_HOSTS = [host.strip() for host in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if host.strip()]
CSRF_TRUSTED_ORIGINS = [origin for origin in os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if origin]
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_otp",
    "django_otp.plugins.otp_totp",
    "accounts.apps.AccountsConfig",
    "audit.apps.AuditConfig",
    "core.apps.CoreConfig",
    "events.apps.EventsConfig",
    "layouts.apps.LayoutsConfig",
    "guests.apps.GuestsConfig",
    "seating.apps.SeatingConfig",
    "communications.apps.CommunicationsConfig",
    "reports.apps.ReportsConfig",
    "checkin.apps.CheckinConfig",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django_otp.middleware.OTPMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.RequestIdMiddleware",
    "core.middleware.ContentSecurityPolicyMiddleware",
    "core.middleware.OrganizationMiddleware",
]
AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/events/"
LOGOUT_REDIRECT_URL = "/accounts/login/"
ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
        "core.context_processors.shell",
    ]},
}]
DATABASES = {"default": {
    "ENGINE": "django.db.backends.postgresql",
    "HOST": os.getenv("POSTGRES_HOST", "db"),
    "PORT": os.getenv("POSTGRES_PORT", "5432"),
    "NAME": os.getenv("POSTGRES_DB", "event_tables"),
    "USER": os.getenv("POSTGRES_USER", "event_tables"),
    "PASSWORD": secret("POSTGRES_PASSWORD"),
    "CONN_MAX_AGE": 60,
    "CONN_HEALTH_CHECKS": True,
}}
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LANGUAGE_CODE = "en"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": BASE_DIR / "private", "base_url": "/private/"}},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
if DEBUG:
    STORAGES["staticfiles"]["BACKEND"] = "django.contrib.staticfiles.storage.StaticFilesStorage"
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 6 * 1024 * 1024
EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = os.getenv("EMAIL_HOST", "maildev")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "1025"))
EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "0") == "1"
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")


def email_password():
    explicit = os.getenv("EMAIL_HOST_PASSWORD", "")
    if explicit:
        return explicit
    if not DEBUG or os.getenv("SENDGRID_API_KEY") or os.getenv("SENDGRID_API_KEY_FILE"):
        return secret("SENDGRID_API_KEY")
    return ""


EMAIL_HOST_PASSWORD = email_password()
EMAIL_TIMEOUT = 20
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "events@example.test")
SERVER_EMAIL = DEFAULT_FROM_EMAIL
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
OTP_TOTP_ISSUER = "Event Tables"
IMPORT_MAX_BYTES = 5 * 1024 * 1024
IMPORT_MAX_ROWS = int(os.getenv("IMPORT_MAX_ROWS", "10000"))
IMPORT_MAX_TICKETS_PER_ROW = int(os.getenv("IMPORT_MAX_TICKETS_PER_ROW", "100"))
EMAIL_RATE_PER_MINUTE = int(os.getenv("EMAIL_RATE_PER_MINUTE", "60"))
SENDGRID_WEBHOOK_PUBLIC_KEY = os.getenv("SENDGRID_WEBHOOK_PUBLIC_KEY", "")
WEBHOOK_TIMESTAMP_TOLERANCE = int(os.getenv("WEBHOOK_TIMESTAMP_TOLERANCE", "300"))
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")
CELERY_TASK_IGNORE_RESULT = True
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_TIMEZONE = "UTC"
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_SOFT_TIME_LIMIT = 270
CELERY_TASK_TIME_LIMIT = 300
CELERY_BROKER_TRANSPORT_OPTIONS = {"visibility_timeout": 3600}
CELERY_TASK_DEFAULT_QUEUE = "default"
CELERY_TASK_ROUTES = {
    "imports.*": {"queue": "imports"},
    "communications.*": {"queue": "mail"},
    "reports.*": {"queue": "reports"},
}
CELERY_BEAT_SCHEDULE = {
    "dispatch-due-mail": {"task": "communications.dispatch_due_mail", "schedule": 30.0},
    "reconcile-abandoned-claims": {"task": "communications.reconcile_abandoned_claims", "schedule": 60.0},
    "expire-holds": {"task": "seating.expire_holds", "schedule": 60.0},
    "retention-cleanup": {"task": "core.retention_cleanup", "schedule": 3600.0},
}
CACHES = {"default": {
    "BACKEND": "django.core.cache.backends.redis.RedisCache",
    "LOCATION": os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0"),
}}
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    SECURE_REDIRECT_EXEMPT = [r"^health/live/$", r"^health/ready/$"]
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = False
    SECURE_HSTS_PRELOAD = False
    SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "same-origin"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"json": {"()": "core.logging.JsonFormatter"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "json"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
