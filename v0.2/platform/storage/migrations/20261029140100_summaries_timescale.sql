-- TimescaleDB ONLY. Mean / min / max / count per 15 minutes and per hour, for numeric readings
-- (ADR-002 section 5). Use them for "measurement" points; for totals use total_15m / total_1h.
-- BAD readings are left out.
--
-- A continuous aggregate is a summary table TimescaleDB keeps up to date by itself:
--   https://tigerdata.com/docs/build/continuous-aggregates/create-a-continuous-aggregate
-- - WITH NO DATA: needed inside a transaction (dbmate runs each file in one); the policy fills it.
-- - materialized_only = false: "real-time" mode, so the newest, not-yet-summarised readings are
--   included when queried (it's off by default since TimescaleDB 2.13):
--   https://www.tigerdata.com/docs/use-timescale/latest/continuous-aggregates/real-time-aggregates
-- - Policy: every run re-summarises the last 7 days, so late data within a week is picked up.
--   Data older than that (e.g. a CSV back-fill) needs:
--     CALL refresh_continuous_aggregate('summary_1h', '<from>', '<to>');
--   https://www.tigerdata.com/docs/reference/timescaledb/continuous-aggregates/add_continuous_aggregate_policy

-- migrate:up
CREATE MATERIALIZED VIEW summary_15m
WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
SELECT series_id, time_bucket(INTERVAL '15 minutes', sensor_time) AS bucket,
       avg(value_num) AS mean, min(value_num) AS min, max(value_num) AS max, count(value_num) AS n
FROM readings
WHERE value_num IS NOT NULL AND quality <> 'BAD'
GROUP BY series_id, bucket
WITH NO DATA;

CREATE MATERIALIZED VIEW summary_1h
WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
SELECT series_id, time_bucket(INTERVAL '1 hour', sensor_time) AS bucket,
       avg(value_num) AS mean, min(value_num) AS min, max(value_num) AS max, count(value_num) AS n
FROM readings
WHERE value_num IS NOT NULL AND quality <> 'BAD'
GROUP BY series_id, bucket
WITH NO DATA;

SELECT add_continuous_aggregate_policy('summary_15m', start_offset => INTERVAL '7 days',
       end_offset => INTERVAL '15 minutes', schedule_interval => INTERVAL '15 minutes');
SELECT add_continuous_aggregate_policy('summary_1h', start_offset => INTERVAL '7 days',
       end_offset => INTERVAL '1 hour', schedule_interval => INTERVAL '1 hour');

GRANT SELECT ON summary_15m, summary_1h TO dtteo_reader;

-- migrate:down
DROP MATERIALIZED VIEW summary_1h;
DROP MATERIALIZED VIEW summary_15m;
