#!/bin/sh
# One backup of the dtteo database, run with:  docker compose run --rm backup
# Writes v0.1/backups/dtteo_<UTC time>_pg<version>_ts<version>.dump (pg_dump custom format).
# The versions are in the name because a restore needs matching PostgreSQL and TimescaleDB
# versions (https://www.tigerdata.com/docs/deploy/self-hosted/backup-and-restore/logical-backup).
# Restore steps: storage/NOTES.md.
set -e
pg=$(psql -tAc "SHOW server_version" | cut -d' ' -f1)
ts=$(psql -tAc "SELECT extversion FROM pg_extension WHERE extname = 'timescaledb'")
file="${BACKUP_DIR:-/backups}/dtteo_$(date -u +%Y%m%dT%H%M%SZ)_pg${pg}_ts${ts:-none}.dump"
pg_dump -Fc -f "$file"
echo "backup written: backups/$(basename "$file")"
