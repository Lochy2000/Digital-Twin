-- Who can do what (ADR-002 section 8). Plain PostgreSQL.
--   dtteo_writer  the historian: add readings and quarantine rows, keep series up to date
--   dtteo_reader  Grafana and other read-only tools: SELECT only
-- These are group roles (no login). The login users (historian, grafana) and their
-- passwords are created once, from .env, by storage/init/10_users.sh, because passwords
-- must not be written in committed files.
-- Grafana: the database user "should have only SELECT permissions on the relevant schemas
-- and tables"  https://grafana.com/docs/grafana/latest/datasources/postgres/configure/

-- migrate:up
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'dtteo_writer') THEN
    CREATE ROLE dtteo_writer NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'dtteo_reader') THEN
    CREATE ROLE dtteo_reader NOLOGIN;
  END IF;
END $$;

GRANT USAGE ON SCHEMA public TO dtteo_writer, dtteo_reader;
GRANT SELECT, INSERT         ON readings, quarantine TO dtteo_writer;
GRANT SELECT, INSERT, UPDATE ON series               TO dtteo_writer;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO dtteo_reader;
-- Tables added by later migrations are readable too, without repeating this.
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO dtteo_reader;

-- migrate:down
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE SELECT ON TABLES FROM dtteo_reader;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM dtteo_writer, dtteo_reader;
REVOKE USAGE ON SCHEMA public FROM dtteo_writer, dtteo_reader;
