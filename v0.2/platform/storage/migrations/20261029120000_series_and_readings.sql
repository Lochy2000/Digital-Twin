-- Series and readings tables (ADR-002 sections 3.2, 3.3). Plain PostgreSQL.
-- A "series" is one site + point; each reading row points to it by series_id.

-- migrate:up
CREATE TABLE series (
  series_id   integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  site        text NOT NULL,
  point_id    text NOT NULL,
  unit        text,                                   -- QUDT ID, e.g. DEG_C; null for modes
  brick_class text NOT NULL,                          -- e.g. brick:Zone_Air_Temperature_Sensor
  kind        text NOT NULL CHECK (kind IN ('measurement', 'total', 'state')),   -- dtteo:valueKind
  first_seen  timestamptz,
  last_seen   timestamptz,
  UNIQUE (site, point_id)
);

CREATE TABLE readings (
  series_id   integer     NOT NULL REFERENCES series (series_id),
  sensor_time timestamptz NOT NULL,                   -- event time (the hypertable is split on this)
  ingest_time timestamptz NOT NULL,                   -- processing time
  value_num   double precision,
  value_text  text,
  value_bool  boolean,
  quality     text NOT NULL CHECK (quality IN ('GOOD', 'SUSPECT', 'BAD')),
  qc          jsonb,                                  -- the message's qc list, if not GOOD
  time_source text NOT NULL CHECK (time_source IN ('device', 'gateway')),
  source      text,
  msg_version smallint NOT NULL,
  CHECK (num_nonnulls(value_num, value_text, value_bool) = 1),   -- exactly one value column
  UNIQUE (series_id, sensor_time)                     -- QoS 1 duplicates: INSERT ... ON CONFLICT DO NOTHING
);

-- migrate:down
DROP TABLE readings;
DROP TABLE series;
