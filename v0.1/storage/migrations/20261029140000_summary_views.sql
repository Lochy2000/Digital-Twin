-- Summaries for "total" and "state" points (ADR-002 section 5). Plain PostgreSQL views:
-- they need LAG()/LEAD(), which continuous aggregates don't allow by default.
-- Views are worked out when queried; fine at feasibility volume (they scan that kind's readings).
-- BAD readings are left out.
--
--   total_steps     every meter reading -> how much it went up since the previous one
--   total_15m/_1h   energy (or any total) used per 15 minutes / hour
--   state_spans     every state reading -> how long that state lasted (until the next reading)
--
-- Meter resets: "Any decrease in the value between two consecutive float samples is interpreted
-- as a counter reset" (Prometheus, resets()), so after a drop the new value itself is the increase.
--   https://prometheus.io/docs/prometheus/latest/querying/functions/
-- date_bin() puts a time in its 15-minute / 1-hour bucket (PostgreSQL 14+).

-- migrate:up
CREATE VIEW total_steps AS
SELECT series_id, sensor_time, value_num,
       CASE WHEN prev IS NULL        THEN NULL                -- first reading: nothing to compare
            WHEN value_num >= prev   THEN value_num - prev
            ELSE value_num                                    -- dropped: meter reset, count from 0
       END AS increase
FROM (SELECT r.series_id, r.sensor_time, r.value_num,
             lag(r.value_num) OVER (PARTITION BY r.series_id ORDER BY r.sensor_time) AS prev
      FROM readings r JOIN series s USING (series_id)
      WHERE s.kind = 'total' AND r.quality <> 'BAD' AND r.value_num IS NOT NULL) t;

CREATE VIEW total_15m AS
SELECT series_id, date_bin('15 minutes', sensor_time, TIMESTAMPTZ '2000-01-01 00:00Z') AS bucket,
       sum(increase) AS increase, count(*) AS steps
FROM total_steps WHERE increase IS NOT NULL GROUP BY 1, 2;

CREATE VIEW total_1h AS
SELECT series_id, date_bin('1 hour', sensor_time, TIMESTAMPTZ '2000-01-01 00:00Z') AS bucket,
       sum(increase) AS increase, count(*) AS steps
FROM total_steps WHERE increase IS NOT NULL GROUP BY 1, 2;

CREATE VIEW state_spans AS
SELECT r.series_id,
       COALESCE(r.value_text, r.value_bool::text) AS state,
       r.sensor_time AS start_time,
       lead(r.sensor_time) OVER (PARTITION BY r.series_id ORDER BY r.sensor_time) AS end_time   -- NULL = still in it
FROM readings r JOIN series s USING (series_id)
WHERE s.kind = 'state' AND r.quality <> 'BAD';

GRANT SELECT ON total_steps, total_15m, total_1h, state_spans TO dtteo_reader;

-- migrate:down
DROP VIEW total_1h;
DROP VIEW total_15m;
DROP VIEW total_steps;
DROP VIEW state_spans;
