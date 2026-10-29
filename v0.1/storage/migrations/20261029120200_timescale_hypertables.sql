-- TimescaleDB ONLY. Turns readings and quarantine into hypertables (split into time chunks).
-- Everything else in storage/migrations is plain PostgreSQL. On plain PostgreSQL (ADR-001's
-- fallback) this file is replaced, e.g. by native partitioning.
-- create_hypertable(..., by_range(...)): the generalised API since TimescaleDB 2.13
--   https://www.tigerdata.com/docs/reference/timescaledb/hypertables/create_hypertable/
-- Compression is NOT switched on (ADR-002 section 11).

-- migrate:up
CREATE EXTENSION IF NOT EXISTS timescaledb;
SELECT create_hypertable('readings', by_range('sensor_time'));
SELECT create_hypertable('quarantine', by_range('ingest_time'));

-- migrate:down
-- A hypertable can't be turned back into a plain table in place. To undo, roll back the
-- two table migrations as well (that drops the tables).
