# Go live on the VPS

The public site is `https://libranconsult.tech`. The server address is `45.151.153.168`. Caddy, in `deploy/Caddyfile`, requests the certificate and proxies to Gunicorn. PostgreSQL and Redis stay on a private Docker network and are not published.

Do this from a shell on the VPS unless a step says it runs on your own computer. Keep `.env.prod` and `secrets/` off git. Do not paste the SendGrid key or the database passwords into a ticket, a chat, or this file.

## 1. Point the domain at the server

At the company that hosts DNS for `libranconsult.tech`, add an address record:

| Field | Value |
|---|---|
| Type | `A` |
| Name | `@` (some panels call this `libranconsult.tech`) |
| Value | `45.151.153.168` |
| TTL | `300` while you are setting up |

Use an A record for the bare domain. A CNAME on the bare domain is not accepted by every DNS host.

`www.libranconsult.tech` is not in the Caddy site. Leave it unset, or people who type `www` will not reach this app. The address to share is `https://libranconsult.tech`.

If the DNS host offers a proxy or CDN, turn that proxy off until the certificate exists. Caddy needs a direct connection from the internet to ports 80 and 443 on this server.

Wait until the name resolves before you start the proxy:

```sh
dig +short libranconsult.tech
```

The answer must be `45.151.153.168`. A stale answer from your own resolver can be checked with `dig +short libranconsult.tech @1.1.1.1`.

## 2. Open only the public ports

Allow SSH, HTTP, and HTTPS. Leave PostgreSQL and Redis closed.

```sh
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
sudo ufw status
```

Port 80 has to stay open. Let's Encrypt uses it to prove control of the domain. Outbound TCP 587 must be allowed as well, because ticket mail goes to `smtp.sendgrid.net`.

Confirm Docker Engine and Compose v2:

```sh
docker version
docker compose version
```

## 3. Copy the project, then build the image

The image name in `.env.prod` is `event-tables:1.0.0`. That tag exists on the computer where it was built. It is not in a public registry, so build it again on the VPS. The guest list, the table-booking PDF, and the secret files are excluded from the image.

On your computer, from the project directory:

```sh
rsync -a --exclude .git --exclude secrets --exclude private --exclude staticfiles --exclude .env.prod \
  ./ USER@45.151.153.168:/opt/event-tables/
scp .env.prod USER@45.151.153.168:/opt/event-tables/.env.prod
scp secrets/*.txt USER@45.151.153.168:/tmp/event-tables-secrets/
```

Replace `USER` with the SSH account on the VPS. On the VPS:

```sh
sudo mkdir -p /opt/event-tables/secrets
sudo mv /tmp/event-tables-secrets/*.txt /opt/event-tables/secrets/
sudo chown -R "$USER:$USER" /opt/event-tables
cd /opt/event-tables
docker build -t event-tables:1.0.0 .
```

Leave `INSTALL_DEV` unset so the production image does not contain the test tools. These files must be present in `secrets/`, one value per file, with no quotes:

- `django_secret_key.txt`
- `postgres_password.txt`
- `postgres_migration_password.txt`
- `postgres_runtime_password.txt`
- `sendgrid_api_key.txt`
- `admin_password.txt`

The app containers run as user `10001`. The database superuser password stays readable only by root. On the VPS:

```sh
sudo chown 10001:10001 secrets/django_secret_key.txt secrets/postgres_migration_password.txt \
  secrets/postgres_runtime_password.txt secrets/sendgrid_api_key.txt secrets/admin_password.txt
sudo chmod 0400 secrets/django_secret_key.txt secrets/postgres_migration_password.txt \
  secrets/postgres_runtime_password.txt secrets/sendgrid_api_key.txt secrets/admin_password.txt
sudo chown root:root secrets/postgres_password.txt
sudo chmod 0400 secrets/postgres_password.txt
```

`.env.prod` already sets the domain, the sender, and the administrator address. The administrator is `brightkoech@libranconsult.tech`. The password is the contents of `secrets/admin_password.txt`. The release step creates that account. Mail is sent as `Kokwet NSW Association <postmaster@communitycore.com.au>` through SendGrid. Authenticate `communitycore.com.au` in SendGrid before the first campaign. The website domain and the sender domain are different on purpose.

## 4. Start the database, migrate, then start the site

Run this only after `dig` shows `45.151.153.168`. If the proxy starts before the name points here, certificate issuance fails and you have to start the proxy again after DNS is correct.

```sh
cd /opt/event-tables
docker compose --env-file .env.prod -f compose.prod.yaml config --quiet
docker compose --env-file .env.prod -f compose.prod.yaml up -d db redis
docker compose --env-file .env.prod -f compose.prod.yaml --profile release run --rm release
docker compose --env-file .env.prod -f compose.prod.yaml run --rm web python manage.py check --deploy
docker compose --env-file .env.prod -f compose.prod.yaml up -d web worker beat proxy
docker compose --env-file .env.prod -f compose.prod.yaml ps
```

If `release` fails, do not start `web`, `worker`, `beat`, or `proxy`. Fix the migration error first.

`check --deploy` reports two warnings, `security.W005` and `security.W021`. Those stay until every name under the domain serves HTTPS. Any other warning should be fixed before inviting staff.

Check the site from the VPS:

```sh
curl -fsS https://libranconsult.tech/health/live/
curl -fsS https://libranconsult.tech/health/ready/
```

Live means the process answered. Ready means PostgreSQL and Redis answered. Ready does not prove that mail was delivered.

## 5. Sign in

Open `https://libranconsult.tech/`. Sign in as `brightkoech@libranconsult.tech` with the password from `secrets/admin_password.txt`.

The first sign-in asks for an authenticator code. Platform administrators, organization owners, and event administrators need that code on every later sign-in. Check-in staff do not.

The header link **Door** is the check-in desk. **Start camera** scans a ticket QR. Search finds a ticket number, an email, or a party. **Send** queues one ticket email to every guest, about 60 messages a minute. Send a message to an address you control before you send the guest list. The button stays hidden while the public address is not `https://` or the mail server is still the local development mailbox.

## 6. The guest list is not in the image

A new production database contains the administrator and an empty event list. The Kalenjin Association Gala 2026 seating that you can see on the development machine is not copied by the steps above. `load_gala` refuses to run when debug is off, and the payment file is not baked into the image.

Load or restore that roster before the doors open, then use **Send** on the Door screen. Do not run `docker compose down -v`. That command deletes the database and the private files.

Backups and a later release are in [operations.md](operations.md).
