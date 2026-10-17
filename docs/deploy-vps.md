# Go live on the VPS

The site is `https://libranconsult.tech`. The server is `45.151.153.168`. The application directory on that server is:

```text
/home/brightkoech/Projects/eventManager
```

Run every command below from that directory, in an SSH session as `brightkoech`, unless a step says it belongs somewhere else. Caddy requests the certificate and proxies to the app. PostgreSQL and Redis stay on a private Docker network.

`.env.prod` and `secrets/` stay on the server. Do not commit them, and do not paste the SendGrid key or the database passwords into a ticket or a chat.

## 1. DNS

At the company that hosts DNS for `libranconsult.tech`, add this record:

| Field | Value |
|---|---|
| Type | `A` |
| Name | `@` |
| Value | `45.151.153.168` |
| TTL | `300` |

Some panels label the name `libranconsult.tech` instead of `@`. Use an A record. The address to share is `https://libranconsult.tech`. This Caddy site does not serve `www.libranconsult.tech`.

If the DNS host has a proxy or CDN, turn that proxy off until the certificate exists. Caddy needs a direct connection to ports 80 and 443.

Check the name before starting the proxy:

```sh
dig +short libranconsult.tech @1.1.1.1
```

The answer must be `45.151.153.168`.

## 2. Firewall

Allow SSH, HTTP, and HTTPS. Leave the database and Redis closed. Port 80 stays open because Let's Encrypt uses it. Ticket mail also needs outbound TCP 587 to `smtp.sendgrid.net`.

```sh
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
sudo ufw status
```

## 3. Install Docker

Skip this section when both commands already print a version:

```sh
docker version
docker compose version
```

On Ubuntu or Debian, install Docker Engine and the Compose plugin:

```sh
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/$(. /etc/os-release && echo "$ID")/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/$(. /etc/os-release && echo "$ID") $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"
```

Log out of SSH and log in again, then confirm:

```sh
docker version
docker compose version
```

The command used later is `docker compose`. That is the plugin. It is separate from the older `docker-compose` program.

## 4. Confirm the project directory

```sh
cd /home/brightkoech/Projects/eventManager
pwd
ls compose.prod.yaml .env.prod Dockerfile
```

`pwd` must print `/home/brightkoech/Projects/eventManager`. The three named files must be in that directory.

When the project is already in that folder, leave it there. A copy is only needed when the files are still on another computer. On that other computer:

```sh
cd /home/brightkoech/Projects/eventManager
ssh brightkoech@45.151.153.168 'mkdir -p /home/brightkoech/Projects/eventManager'
rsync -a --exclude .git --exclude secrets --exclude private --exclude staticfiles --exclude .env.prod \
  ./ brightkoech@45.151.153.168:/home/brightkoech/Projects/eventManager/
scp .env.prod secrets/*.txt brightkoech@45.151.153.168:/tmp/event-tables-upload/
```

Then, on the VPS:

```sh
cd /home/brightkoech/Projects/eventManager
mkdir -p secrets
mv /tmp/event-tables-upload/.env.prod .env.prod
mv /tmp/event-tables-upload/*.txt secrets/
```

`./` in the `rsync` command is the directory you are in. Start that command only after `cd` has entered the project. Running it from `/home/brightkoech` sends the home directory, including `.ssh` and `.bashrc`.

## 5. Secrets and the image

These files must sit in `secrets/`, one value each, with no quotes:

- `django_secret_key.txt`
- `postgres_password.txt`
- `postgres_migration_password.txt`
- `postgres_runtime_password.txt`
- `sendgrid_api_key.txt`
- `admin_password.txt`

The app containers, including the release step, run as user `10001`. That user has to read every secret file, including the database superuser password. The database container starts as root, so it can still read a file owned by `10001`.

```sh
cd /home/brightkoech/Projects/eventManager
sudo chown 10001:10001 secrets/django_secret_key.txt secrets/postgres_password.txt \
  secrets/postgres_migration_password.txt secrets/postgres_runtime_password.txt \
  secrets/sendgrid_api_key.txt secrets/admin_password.txt
sudo chmod 0400 secrets/django_secret_key.txt secrets/postgres_password.txt \
  secrets/postgres_migration_password.txt secrets/postgres_runtime_password.txt \
  secrets/sendgrid_api_key.txt secrets/admin_password.txt
docker build -t event-tables:1.0.0 .
```

Leave `INSTALL_DEV` unset. The production image then omits the test tools. The guest list and the table-booking PDF are also left out of the image.

`.env.prod` already contains:

| Name | Value |
|---|---|
| `APP_IMAGE` | `event-tables:1.0.0` |
| `DOMAIN` | `libranconsult.tech` |
| `ACME_EMAIL` | `postmaster@communitycore.com.au` |
| `DEFAULT_FROM_EMAIL` | `Kokwet NSW Association <postmaster@communitycore.com.au>` |
| `ADMIN_EMAIL` | `brightkoech@libranconsult.tech` |
| Mail host | `smtp.sendgrid.net`, port `587`, TLS on, username `apikey` |

The administrator password is the contents of `secrets/admin_password.txt`. The SendGrid key is the contents of `secrets/sendgrid_api_key.txt`. Authenticate `communitycore.com.au` in SendGrid before the first campaign. The website domain and the sender domain are different.

## 6. Start the site

Start the proxy only after `dig` shows `45.151.153.168`.

```sh
cd /home/brightkoech/Projects/eventManager
docker compose --env-file .env.prod -f compose.prod.yaml config --quiet
docker compose --env-file .env.prod -f compose.prod.yaml up -d db redis
docker compose --env-file .env.prod -f compose.prod.yaml --profile release run --rm release
docker compose --env-file .env.prod -f compose.prod.yaml run --rm web python manage.py check --deploy
docker compose --env-file .env.prod -f compose.prod.yaml up -d web worker beat proxy
docker compose --env-file .env.prod -f compose.prod.yaml ps
```

If `release` fails, leave `web`, `worker`, `beat`, and `proxy` stopped and fix the migration error first. The release creates the database roles, applies migrations, collects static files, and creates the administrator `brightkoech@libranconsult.tech`.

`check --deploy` reports `security.W005` and `security.W021`. Those two warnings stay until every name under the domain serves HTTPS. Fix any other warning before inviting staff.

```sh
curl -fsS https://libranconsult.tech/health/live/
curl -fsS https://libranconsult.tech/health/ready/
```

Live means the process answered. Ready means PostgreSQL and Redis answered. Ready does not prove that mail was delivered.

## 7. Sign in and the door

Open `https://libranconsult.tech/`. Sign in as `brightkoech@libranconsult.tech` with the password from `secrets/admin_password.txt`.

The first sign-in asks for an authenticator code. Platform administrators, organization owners, and event administrators need that code on later sign-ins. Check-in staff do not.

**Door** in the header is the check-in desk. **Start camera** scans a ticket QR. Search finds a ticket number, an email, or a party. **Send** queues one ticket email to every guest, about 60 messages a minute. Send one message to an address you control before sending the guest list.

## 8. Guest list

A new production database contains the administrator and an empty event list. Load the payment file from the project directory. It is not inside the image. The command seats every row and sends the ticket emails, about 60 a minute.

```sh
cd /home/brightkoech/Projects/eventManager
docker compose --env-file .env.prod -f compose.prod.yaml run --rm \
  -v "$PWD/core/management/commands/load_gala.py:/app/core/management/commands/load_gala.py:ro" \
  -v "$PWD/guests/gala.py:/app/guests/gala.py:ro" \
  -v "$PWD/templates/communications/email/seating.html:/app/templates/communications/email/seating.html:ro" \
  -v "$PWD/unified_payments_with_ids.csv:/tmp/payments.csv:ro" \
  web python manage.py load_gala --csv /tmp/payments.csv
```

Running it again does not create a second set of tickets or send the campaign twice. `docker compose down -v` deletes the database and the private files. Backups and a later release are in [operations.md](operations.md).
