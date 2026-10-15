# Event Table Management System — specification and container starter

Start with [SPECIFICATION.md](SPECIFICATION.md). It contains the functional scope, data model, concurrency rules, CSV behavior, layout editor, reservations, communications, reports, security, operations and 20 acceptance scenarios.

**Delivery boundary:** the Django project is a minimal infrastructure scaffold. Event CRUD, guest import, seating editor, reservation services, guest pages, reports, mail jobs, MFA and webhook verification are specified but not implemented. The `/` route intentionally has no application page yet. Available routes are `/admin/`, `/health/live/` and `/health/ready/`.

## Included files

| File | Purpose |
|---|---|
| `compose.dev.yaml` | Local Django, PostgreSQL, Redis, Celery worker/beat and MailDev |
| `compose.prod.yaml` | Registry image, Gunicorn, PostgreSQL, Redis, worker/beat, release job and Caddy HTTPS |
| `Dockerfile` | Non-root Python runtime for web and background services |
| `config/` | Django/Celery settings, health routes and WSGI |
| `deploy/Caddyfile` | Automatic public HTTPS and upload size limit |
| `.env.prod.example` | Non-secret production configuration template |
| `guests.example.csv` | Required import format example |

## Development

Prerequisites: Docker Engine/Desktop with Linux containers and Docker Compose v2. Run from this directory:

```sh
docker compose -f compose.dev.yaml config --quiet
docker compose -f compose.dev.yaml up --build -d
docker compose -f compose.dev.yaml exec web python manage.py createsuperuser
docker compose -f compose.dev.yaml exec web python manage.py check
```

Open Django admin at `http://localhost:8000/admin/` and MailDev at `http://localhost:1080`. The browser-accessible ports bind only to loopback. Database, Redis and SMTP have no published host ports. Development credentials are deliberately local-only. The migrate service completes before web/worker/beat start. Web reloads source edits; restart the worker after changing task code.

Send a captured development email:

```sh
docker compose -f compose.dev.yaml exec web python manage.py shell -c "from django.core.mail import send_mail; send_mail('SMTP smoke test', 'Development email delivery works.', None, ['guest@example.test'])"
docker compose -f compose.dev.yaml exec worker celery -A config inspect ping
docker compose -f compose.dev.yaml logs --tail=100 web worker beat
docker compose -f compose.dev.yaml down
```

Named volumes preserve database and private files when services stop. `down -v` deletes them and must only be used for an intentional reset. Development source is bind mounted; production source is baked into the image.

## Production preparation

Production Compose is a single-host deployment template. Complete application implementation and staging acceptance before using it for a real event. No infrastructure was deployed by generating these files.

1. Provision a Linux host, Docker/Compose, persistent storage and a domain pointing to the host. Permit inbound TCP 80/443 for Caddy. Permit outbound HTTPS/DNS and SendGrid TCP 587. Keep database/broker ports private.
2. Resolve and test exact patched dependency versions; commit a lock file with hashes and pin release base/service images by digest. Included version families are intentionally upgradeable starter constraints, not a reproducible dependency lock.
3. Build and publish the tested application image through your CI/registry workflow. For example: `docker build -t registry.example.com/event-tables:1.0.0 .`, followed by your authorized image push. Configure `APP_IMAGE` to the tested release or digest.
4. Copy `.env.prod.example` to `.env.prod` and replace every placeholder. Authenticate the SendGrid sender domain; create a restricted Mail Send API key.
5. Create `secrets/django_secret_key.txt`, `secrets/postgres_password.txt`, and `secrets/sendgrid_api_key.txt` on the host. Each contains only its secret. Use a cryptographically random Django key of at least 50 characters and a strong independent database password. Never use development credentials. Secrets and env files are excluded from Docker builds and git.
6. Compose file secrets are mounted files, not an encrypted secret manager. Protect the host directory, backups and Docker access. Mounted files must be readable by container UID 10001; for Linux file mounts, use deliberate host ownership/ACLs (e.g. UID 10001 and mode 0400), and verify readability without printing the values. The PostgreSQL entrypoint starts as root and can read its password file.
7. Configure off-host backups, alerting and a restore rehearsal. Implement the specified tenant authorization, MFA, throttling, audit, upload validation and durable outbox before launch.

The scaffold's official PostgreSQL image initializes `POSTGRES_USER` as a database superuser. For a production application, provision a separate non-superuser runtime role and a migration owner, grant only required schema/table/sequence privileges, and provide distinct release/runtime credentials by adapting the app environment and secrets. Do not expose generic Django superuser access to event coordinators. Database-role separation is a release-hardening requirement, not implemented in this scaffold.

## First production release

Run these commands from the release directory, after configuration and secret files exist:

```sh
docker compose --env-file .env.prod -f compose.prod.yaml config --quiet
docker compose --env-file .env.prod -f compose.prod.yaml pull
docker compose --env-file .env.prod -f compose.prod.yaml up -d db redis
docker compose --env-file .env.prod -f compose.prod.yaml --profile release run --rm release
docker compose --env-file .env.prod -f compose.prod.yaml run --rm web python manage.py check --deploy
docker compose --env-file .env.prod -f compose.prod.yaml up -d web worker beat proxy
docker compose --env-file .env.prod -f compose.prod.yaml exec web python manage.py createsuperuser
docker compose --env-file .env.prod -f compose.prod.yaml ps
```

The release job runs migrations and collects static files once. Never run migrations in every web/worker entrypoint. The web health check verifies PostgreSQL and Redis; it does not confirm migration completeness, worker health or successful mail delivery. Review any `check --deploy` warning and its rationale before launching. HSTS subdomain inclusion and preload are intentionally disabled until the domain owner confirms that every affected subdomain supports HTTPS.

Caddy provisions certificates for the configured public domain. Web has no published port; Caddy supplies trusted forwarding headers. WhiteNoise serves collected static assets. Private files have no public media route; implement authenticated download views. Internal backend networking isolates DB/Redis from direct inbound access; web and workers additionally have egress access for SendGrid. Redis has no password in this isolated single-host starter, so only trusted application containers should join its network; add ACL credentials/TLS if the trust or network model changes.

Run only one beat service. The starter has no periodic business jobs registered yet. Celery result payloads are disabled; implement persisted job progress in the application database. A worker ping can be checked with the same `celery -A config inspect ping` command used in development, using the production Compose flags.

## Subsequent release and rollback

This baseline uses a maintenance window. Take a verified backup, stop proxy/web/worker/beat, update `APP_IMAGE`, pull the new image, run the release job, run deployment checks, then start services and smoke-test login, health, a job and email. Stopping all writers avoids schema/asset conflicts while migrations run; static files are shared and changed by `collectstatic`.

Do not start services if the release job fails. Investigate the failed migration and database state. Reverting only the image is safe only if schema compatibility was tested. Otherwise restore the matched database/private-files backup with the previous image and static build. Never automate destructive reverse migrations without review. Zero-downtime releases require backward-compatible migrations, versioned static assets and a different rollout design.

## Backup and recovery

- Schedule a daily PostgreSQL `pg_dump -Fc`, encrypted off-host copy, and private-data backup; coordinate the files and database under maintenance or with a consistent snapshot strategy.
- Keep dump data out of terminal output. Use a dedicated backup identity and do not put passwords in command arguments.
- Retain release image references, configuration (without exposed secrets), and required secret recovery material in the organization's secret store.
- Keep Caddy data if avoiding certificate reissuance matters. Redis/beat state is secondary to PostgreSQL; rebuild pending jobs through database reconciliation once implemented.
- Restore into a clean isolated environment, validate row counts and sample seat assignments, verify private-file downloads and check that no real email sends occur during recovery tests.
- Baseline targets are RPO 24h / RTO 4h; measure them. Enable PITR for a tighter database RPO.

Never use production `down -v` as a deployment step. Rotating `postgres_password.txt` does not change an existing database user's password: rotate the role password in PostgreSQL and its application secret together. Rotate SendGrid and Django keys using a planned procedure; Django key changes can invalidate sessions and signed guest links.

## Verification performed on the generated package

- Both development and production Compose files passed `docker compose ... config --quiet` (production used `.env.prod.example`).
- Container build and runtime smoke tests were not executed: this session was denied access to the Docker Desktop Linux-engine pipe.
- Consequently, image pulls/builds, database migrations, mail delivery, HTTPS issuance and application runtime remain to be verified on your Docker host.
- The included functional acceptance cases apply to the future application; they are not represented as passing tests of this scaffold.

## Reference behavior

The configuration follows [Docker Compose production guidance](https://docs.docker.com/compose/how-tos/production/) and [file-mounted Compose secrets](https://docs.docker.com/compose/how-tos/use-secrets/). Email uses [MailDev's SMTP/web ports](https://maildev.github.io/maildev/docs/quickstart/) in development and [SendGrid SMTP integration](https://www.twilio.com/docs/sendgrid/for-developers/sending-email/integrating-with-the-smtp-api) in production. Review the [Django deployment checklist](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/) for each release.
