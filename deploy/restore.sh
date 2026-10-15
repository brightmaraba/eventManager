#!/bin/sh
# Restore an encrypted backup into an isolated database. Email sending stays off.
# Required: BACKUP_PASSPHRASE, RESTORE_DATABASE (must not be the live database name).
# Does not drop the live database or Docker volumes.
set -eu

archive="${1:?Usage: deploy/restore.sh <encrypted-archive>}"
compose_file="${COMPOSE_FILE:-compose.prod.yaml}"
env_file="${ENV_FILE:-.env.prod}"
restore_db="${RESTORE_DATABASE:?Set RESTORE_DATABASE to an isolated database name}"
case "$restore_db" in
  event_tables|*[!A-Za-z0-9_]*) echo "Refusing restore database name: $restore_db" >&2; exit 1 ;;
esac

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
openssl enc -d -aes-256-cbc -pbkdf2 -pass env:BACKUP_PASSPHRASE -in "$archive" | tar -xf - -C "$work"
dump="$(find "$work" -name 'event_tables-*.dump' -print -quit)"
files="$(find "$work" -name 'private-*.tar' -print -quit)"
docker compose --env-file "$env_file" -f "$compose_file" exec -T db \
  psql -U "${POSTGRES_ADMIN_USER:-event_tables}" -d postgres -c "CREATE DATABASE $restore_db"
docker compose --env-file "$env_file" -f "$compose_file" exec -T db \
  pg_restore -U "${POSTGRES_ADMIN_USER:-event_tables}" -d "$restore_db" --no-owner < "$dump"
echo "Restored $restore_db from $dump"
echo "Private files archive: $files"
echo "Leave EMAIL_BACKEND unset or pointed at a sink before starting the restored application."
