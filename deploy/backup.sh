#!/bin/sh
# Logical backup of the application database and private files.
# Run from the deployment directory. Does not delete volumes.
# Required: BACKUP_PASSPHRASE, COMPOSE_FILE, and the Compose project already running.
set -eu

output_dir="${1:?Usage: deploy/backup.sh <output-directory>}"
compose_file="${COMPOSE_FILE:-compose.prod.yaml}"
env_file="${ENV_FILE:-.env.prod}"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$output_dir"
dump="$output_dir/event_tables-$stamp.dump"
files="$output_dir/private-$stamp.tar"
encrypted="$output_dir/event_tables-$stamp.tar.enc"

docker compose --env-file "$env_file" -f "$compose_file" exec -T db \
  pg_dump -U "${POSTGRES_ADMIN_USER:-event_tables}" -Fc event_tables > "$dump"
docker compose --env-file "$env_file" -f "$compose_file" exec -T web \
  tar -C /app -cf - private > "$files"
tar -cf - -C "$output_dir" "$(basename "$dump")" "$(basename "$files")" \
  | openssl enc -aes-256-cbc -pbkdf2 -salt -pass env:BACKUP_PASSPHRASE -out "$encrypted"
rm -f "$dump" "$files"
echo "$encrypted"
