-- Quarantine table (ADR-002 section 3.4). Plain PostgreSQL.
-- Holds every dt/v1/quarantine/# message, plus anything the historian itself can't store.

-- migrate:up
CREATE TABLE quarantine (
  ingest_time timestamptz NOT NULL,
  site        text NOT NULL,
  stage       text NOT NULL CHECK (stage IN ('decode', 'map', 'normalise', 'internal',   -- from the gateway
                                             'store')),   -- the historian couldn't store it (e.g. unknown series)
  reason      text NOT NULL,
  topic       text,
  source      text,
  device      text,
  field       text,
  value       jsonb,
  raw         text NOT NULL,                          -- the original message, for replay
  msg_version smallint NOT NULL
);

-- migrate:down
DROP TABLE quarantine;
