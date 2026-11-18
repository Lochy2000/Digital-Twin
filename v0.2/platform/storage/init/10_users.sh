#!/bin/sh
# Creates the login users ONCE, the first time the database container starts with an empty
# data volume (that's when /docker-entrypoint-initdb.d scripts run:
# https://docs.docker.com/guides/postgresql/advanced-configuration-and-initialization).
# Passwords come from .env. Table permissions are granted by storage/migrations, not here.
# To change a password later:  ALTER ROLE historian PASSWORD '...';
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
     -v hist_pw="$HISTORIAN_DB_PASSWORD" -v graf_pw="$GRAFANA_DB_PASSWORD" <<'EOSQL'
CREATE ROLE dtteo_writer NOLOGIN;
CREATE ROLE dtteo_reader NOLOGIN;
CREATE ROLE historian LOGIN PASSWORD :'hist_pw' IN ROLE dtteo_writer;
CREATE ROLE grafana   LOGIN PASSWORD :'graf_pw' IN ROLE dtteo_reader;
EOSQL
