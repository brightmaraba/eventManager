# Operations

## Startup

Development:

```sh
docker compose -f compose.dev.yaml up --build -d
docker compose -f compose.dev.yaml exec web python manage.py seed_demo
```

Production, after `.env.prod` and the secret files exist:

```sh
docker compose --env-file .env.prod -f compose.prod.yaml config --quiet
docker compose --env-file .env.prod -f compose.prod.yaml up -d db redis
docker compose --env-file .env.prod -f compose.prod.yaml --profile release run --rm release
docker compose --env-file .env.prod -f compose.prod.yaml run --rm web python manage.py check --deploy
docker compose --env-file .env.prod -f compose.prod.yaml up -d web worker beat proxy
```

`release_prepare` creates `event_tables_migrate` and `event_tables_app`, grants the runtime role table and sequence access without `CREATE`, then migrates and collects static files. Web, worker, and beat use the runtime role. Do not run migrations from those processes.

Privileged production roles require TOTP: platform administrator, organization owner, and event administrator. Development skips that gate only while `DJANGO_DEBUG=1`. Check-in staff do not require TOTP and cannot export unless the grant says so.

## Backups

`deploy/backup.sh` writes an encrypted archive containing a custom-format `pg_dump` and a tar of `/app/private`. `deploy/restore.sh` restores into `RESTORE_DATABASE`, which must be a new database name and cannot be `event_tables`. Leave email pointed at MailDev or another sink during a restore rehearsal.

A local rehearsal on 15 October 2026 dumped the development database, restored it into `event_tables_restore`, read the event and seat counts, and dropped that database. The rehearsal took 5.75 seconds. It did not measure a full production dataset, so the operational targets remain RPO 24 hours and RTO 4 hours. Do not use `down -v` as a backup or rollback step.

## Rollback

Stop proxy, web, worker, and beat. Restore the matching database and private-file backup, then start the previous image. Reversing a migration automatically is not part of the release job. Redis can be rebuilt from the PostgreSQL outbox and hold rows: pending mail stays in `EmailDelivery`, and an expired hold is released inside the next assignment transaction even when beat is stopped.

## Checks that are still open

`manage.py check --deploy` against the development secret reports `security.W009` because that key is the local development key. HSTS subdomain inclusion and preload remain warnings on purpose until every subdomain is known to be HTTPS-only. No public host, SendGrid staging send, or production restore has been run. Playwright browser binaries are not installed; the layout, import, check-in, and export pages were exercised in a desktop browser and the event page was opened at a 390-pixel width.
