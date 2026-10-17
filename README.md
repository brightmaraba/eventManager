# Event Table Management System

Django application for event setup, guest import, table seating, publication snapshots, guest links, check-in, mail, and printouts. Day-to-day use is in [docs/user-guide.md](docs/user-guide.md). Backup, rollback, and database roles are in [docs/operations.md](docs/operations.md).

You need Docker Engine with Linux containers and Docker Compose v2. Run every command from this directory.

## Run locally

Development Compose builds the app, applies migrations, then starts the web server, Celery worker, and Celery beat. PostgreSQL, Redis, and SMTP stay on the Compose network. Only the web UI and MailDev are published, and only on loopback.

```sh
docker compose -f compose.dev.yaml config --quiet
docker compose -f compose.dev.yaml up --build -d
docker compose -f compose.dev.yaml exec web python manage.py seed_demo
```

Open the app at [http://127.0.0.1:8000/](http://127.0.0.1:8000/). The seed command creates a demo owner:

| | |
|---|---|
| Email | `owner@example.test` |
| Password | `S3cure-pass-word` |
| Organization | North Hall |
| Event | Spring dinner |

Development login does not ask for a second factor because `DJANGO_DEBUG=1`. Captured mail is at [http://127.0.0.1:1080/](http://127.0.0.1:1080/). Messages are delivered to MailDev, not to the public internet.

Useful checks:

```sh
docker compose -f compose.dev.yaml ps
docker compose -f compose.dev.yaml logs --tail=100 web worker beat
docker compose -f compose.dev.yaml exec web python manage.py check
docker compose -f compose.dev.yaml exec web pytest -q
```

The default test run skips browser and reference-workload tests. UI checks need Playwright's browsers inside the web container. Install them once as root, then run the suite with the browser cache visible to that user:

```sh
docker compose -f compose.dev.yaml exec -u root web python -m playwright install --with-deps chromium firefox webkit
docker compose -f compose.dev.yaml exec -u root -e PLAYWRIGHT_BROWSERS_PATH=/root/.cache/ms-playwright -e DJANGO_ALLOW_ASYNC_UNSAFE=true web pytest -o addopts="-ra --tb=short" --reuse-db -m browser tests/browser --browser chromium --browser firefox --browser webkit
```

The 1,000-table timing check is separate:

```sh
docker compose -f compose.dev.yaml exec web pytest -o addopts="-ra --tb=short" -m slow tests/test_ui_workload.py -s
```

Tests must run inside the web container. The database host name is `db`.

Stop the stack without deleting data:

```sh
docker compose -f compose.dev.yaml down
```

`docker compose -f compose.dev.yaml down -v` deletes the database, Redis data, and private files. Use it only when you intend to reset the local environment. Source edits are bind-mounted, so the web process reloads them. Restart the worker after changing task code:

```sh
docker compose -f compose.dev.yaml restart worker beat
```

## Run in production

The VPS steps, including the DNS record for `libranconsult.tech`, are in [docs/deploy-vps.md](docs/deploy-vps.md).

Production Compose expects a published application image, a public domain, and secret files on the host. It was not deployed by this repository. Web has no published port. Caddy serves HTTPS on ports 80 and 443 and proxies to Gunicorn. The database and Redis stay on a private network.

The release job is the only process that migrates and collects static files. After that, the web, worker, and beat processes connect as the non-superuser role `event_tables_app`. Migrations use `event_tables_migrate`. The PostgreSQL superuser `event_tables` is used only to create those roles.

### 1. Build and publish the image

Build from a tested commit. The production image must be built with `INSTALL_DEV` left at its default of `0`.

```sh
docker build -t registry.example.com/event-tables:1.0.0 .
docker push registry.example.com/event-tables:1.0.0
```

### 2. Configure the host

Point the domain at the host. Allow inbound TCP 80 and 443. Allow outbound HTTPS, DNS, and SendGrid on TCP 587. Keep database and Redis ports closed to the internet.

```sh
cp .env.prod.example .env.prod
```

Edit `.env.prod`:

| Variable | Purpose |
|---|---|
| `APP_IMAGE` | Registry image and tag or digest from the build above |
| `DOMAIN` | Public hostname, such as `events.example.com` |
| `ACME_EMAIL` | Address Caddy uses for certificate notices |
| `DEFAULT_FROM_EMAIL` | Authenticated SendGrid sender |

Create `secrets/` and put one secret in each file, with no extra whitespace or quotes:

```sh
mkdir -p secrets
openssl rand -base64 48 > secrets/django_secret_key.txt
openssl rand -base64 32 > secrets/postgres_password.txt
openssl rand -base64 32 > secrets/postgres_migration_password.txt
openssl rand -base64 32 > secrets/postgres_runtime_password.txt
```

Put the restricted SendGrid Mail Send API key in `secrets/sendgrid_api_key.txt`. Authenticate the sender domain in SendGrid before the first campaign.

The application containers run as UID 10001. On Linux, make the Django, migration, runtime, and SendGrid files readable by that user and by nobody else:

```sh
chown 10001:10001 secrets/django_secret_key.txt secrets/postgres_migration_password.txt secrets/postgres_runtime_password.txt secrets/sendgrid_api_key.txt
chmod 0400 secrets/django_secret_key.txt secrets/postgres_migration_password.txt secrets/postgres_runtime_password.txt secrets/sendgrid_api_key.txt
chown root:root secrets/postgres_password.txt
chmod 0400 secrets/postgres_password.txt
```

The database entrypoint starts as root and reads `postgres_password.txt`. Do not commit `secrets/` or `.env.prod`.

### 3. Start the database, migrate, then start the app

```sh
docker compose --env-file .env.prod -f compose.prod.yaml config --quiet
docker compose --env-file .env.prod -f compose.prod.yaml pull
docker compose --env-file .env.prod -f compose.prod.yaml up -d db redis
docker compose --env-file .env.prod -f compose.prod.yaml --profile release run --rm release
docker compose --env-file .env.prod -f compose.prod.yaml run --rm web python manage.py check --deploy
docker compose --env-file .env.prod -f compose.prod.yaml up -d web worker beat proxy
docker compose --env-file .env.prod -f compose.prod.yaml ps
```

If `release` fails, do not start `web`, `worker`, `beat`, or `proxy`. Fix the migration error first.

Create the first platform administrator. That account needs a TOTP device on the next login. Organization owners and event administrators also require TOTP. Check-in staff do not.

```sh
docker compose --env-file .env.prod -f compose.prod.yaml exec web python manage.py createsuperuser
```

Open `https://<DOMAIN>/`. Health checks are `https://<DOMAIN>/health/live/` and `https://<DOMAIN>/health/ready/`. Ready means PostgreSQL and Redis answered. It does not prove that migrations finished or that mail was delivered.

HSTS subdomain inclusion and preload stay off until every subdomain on that domain serves HTTPS. Review any other `check --deploy` warning before inviting staff.

Send mail only to addresses you control until the sender domain and webhook are verified. Guest addresses in tests and demos should use `@example.test`.

### 4. Ship a later release

Take a backup first. See [docs/operations.md](docs/operations.md). Then stop the writers, replace `APP_IMAGE`, and migrate before starting the new processes:

```sh
docker compose --env-file .env.prod -f compose.prod.yaml stop proxy web worker beat
docker compose --env-file .env.prod -f compose.prod.yaml pull
docker compose --env-file .env.prod -f compose.prod.yaml --profile release run --rm release
docker compose --env-file .env.prod -f compose.prod.yaml run --rm web python manage.py check --deploy
docker compose --env-file .env.prod -f compose.prod.yaml up -d web worker beat proxy
```

Run only one beat service. Do not run `down -v` as part of a release. That command deletes the database and private files.
