"""
E5: storage growth and dashboard query speed with a year of data.

Fills a copy of the database (dtteo_e5, same schema) with one year of readings, one a minute,
for each of the 10 points in the asset model (5.26 million rows), then:
  - measures the bytes per reading (table + indexes);
  - times the dashboard's own SQL (grafana/dashboards/dtteo-overview.json) over 24 h, 7 d, 30 d
    and 365 d, 5 runs each. "Hourly mean" reads summary_1h, a TimescaleDB continuous aggregate,
    which this PostgreSQL has not got: it is run here on the raw readings instead (the slow case).

    python experiments/e5_storage.py
"""
from __future__ import annotations

import statistics as st
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import harness as h  # noqa: E402
import psycopg  # noqa: E402

E5_URL = h.DB_URL.rsplit("/", 1)[0] + "/dtteo_e5"
END = "2026-11-01 00:00+00"
RANGES = {"24 h": "1 day", "7 d": "7 days", "30 d": "30 days", "365 d": "365 days"}
RUNS = 5

FILL = """
INSERT INTO readings (series_id, sensor_time, ingest_time, value_num, value_text, quality, time_source, source, msg_version)
SELECT s.series_id, t, t + interval '1 second',
       CASE s.kind WHEN 'measurement' THEN 20 + 3 * sin(extract(epoch FROM t) / 86400 * 2 * pi()) + random() * 0.2
                   WHEN 'total' THEN extract(epoch FROM t - TIMESTAMPTZ '2025-11-01') / 3600 * 1.5 END,
       CASE s.kind WHEN 'state' THEN (ARRAY['heat', 'cool', 'off'])[1 + (extract(epoch FROM t)::bigint / 10800) % 3] END,
       CASE WHEN random() < 0.002 THEN 'SUSPECT' ELSE 'GOOD' END, 'device', 'acme:acme_hvac_0001', 2
FROM series s, generate_series(TIMESTAMPTZ '2025-11-01 00:00+00', TIMESTAMPTZ '2026-11-01 00:00+00' - interval '1 minute',
                               interval '1 minute') t
"""

POINTS = "SELECT string_agg(quote_literal(point_id), ',') FROM series WHERE kind = 'measurement'"


def queries(rng: str, points: str) -> dict[str, str]:
    tf = lambda col: f"{col} BETWEEN TIMESTAMPTZ '{END}' - INTERVAL '{rng}' AND TIMESTAMPTZ '{END}'"
    return {
        "Measurements (every reading), 1 point": f"""
            SELECT r.sensor_time AS time, s.point_id AS metric, r.value_num AS value
            FROM readings r JOIN series s USING (series_id)
            WHERE s.point_id IN ('unit1.zone_air_temp') AND r.quality <> 'BAD' AND {tf('r.sensor_time')} ORDER BY 1""",
        "Measurements (every reading), all 8 points": f"""
            SELECT r.sensor_time AS time, s.point_id AS metric, r.value_num AS value
            FROM readings r JOIN series s USING (series_id)
            WHERE s.point_id IN ({points}) AND r.quality <> 'BAD' AND {tf('r.sensor_time')} ORDER BY 1""",
        "Hourly mean, all 8 points (raw, no continuous aggregate)": f"""
            SELECT date_bin('1 hour', r.sensor_time, TIMESTAMPTZ '2000-01-01') AS time, s.point_id, avg(r.value_num)
            FROM readings r JOIN series s USING (series_id)
            WHERE s.point_id IN ({points}) AND r.quality <> 'BAD' AND {tf('r.sensor_time')} GROUP BY 1, 2 ORDER BY 1""",
        "Energy used per hour (total_1h view)": f"""
            SELECT t.bucket AS time, s.point_id AS metric, t.increase AS value
            FROM total_1h t JOIN series s USING (series_id) WHERE {tf('t.bucket')} ORDER BY 1""",
        "Mode": f"""
            SELECT r.sensor_time AS time, r.value_text AS mode FROM readings r JOIN series s USING (series_id)
            WHERE s.point_id = 'unit1.mode_status' AND r.quality <> 'BAD' AND {tf('r.sensor_time')} ORDER BY 1""",
        "Readings by quality": f"""
            SELECT count(*) FILTER (WHERE quality = 'GOOD'), count(*) FILTER (WHERE quality = 'SUSPECT'),
                   count(*) FILTER (WHERE quality = 'BAD') FROM readings WHERE {tf('sensor_time')}""",
    }


def main():
    h.sql("DROP DATABASE IF EXISTS dtteo_e5")
    h.sql("CREATE DATABASE dtteo_e5 TEMPLATE dtteo")
    with psycopg.connect(E5_URL, autocommit=True) as c:
        c.execute("TRUNCATE readings, quarantine")
        t = time.perf_counter()
        c.execute(FILL)
        fill_s = time.perf_counter() - t
        c.execute("VACUUM ANALYZE readings")
        n = c.execute("SELECT count(*) FROM readings").fetchone()[0]
        table, idx, total = c.execute("""SELECT pg_table_size('readings'), pg_indexes_size('readings'),
                                         pg_total_relation_size('readings')""").fetchone()
        points = c.execute(POINTS).fetchone()[0]
        size = [{"rows": n, "points": 10, "fill_seconds": round(fill_s, 1), "table_bytes": table, "index_bytes": idx,
                 "total_bytes": total, "bytes_per_reading": round(total / n, 1),
                 "table_bytes_per_reading": round(table / n, 1), "index_bytes_per_reading": round(idx / n, 1)}]
        h.write_csv("e5_size.csv", size)
        print(size[0], flush=True)

        out, plans = [], []
        for label, rng in RANGES.items():
            for name, q in queries(rng, points).items():
                times, rows = [], 0
                for _ in range(RUNS):
                    t = time.perf_counter()
                    rows = len(c.execute(q).fetchall())
                    times.append(time.perf_counter() - t)
                out.append({"range": label, "query": name, "rows_returned": rows, "median_ms": round(1000 * st.median(times), 1),
                            "max_ms": round(1000 * max(times), 1), "first_ms": round(1000 * times[0], 1)})
                print(out[-1], flush=True)
                if label == "365 d":
                    plan = c.execute("EXPLAIN (ANALYZE, BUFFERS, COSTS OFF) " + q).fetchall()
                    plans.append(f"--- {name} ({label})\n" + "\n".join(p[0] for p in plan))
        h.write_csv("e5_queries.csv", out)
        (h.RESULTS / "e5_query_plans_365d.txt").write_text("\n\n".join(plans))


if __name__ == "__main__":
    print(h.stamp(), "E5")
    main()
