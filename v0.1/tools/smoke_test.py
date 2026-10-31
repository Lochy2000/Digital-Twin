"""
Smoke test: is the whole running stack working, end to end?

    python tools\\smoke_test.py          (from v0.1, after "docker compose up -d")

What it checks, in about 10 seconds:
  1. Migrations: all files in storage/migrations are applied.
  2. Reading path: a test Acme message on raw/... comes out of the gateway, through the
     historian, into the readings table (as unit1.zone_air_temp, quality GOOD).
  3. Quarantine path: a field nobody has mapped ends up in the quarantine table.
  4. Summaries: the TimescaleDB summary (summary_1h) and the energy view (total_1h) answer.
  5. Grafana: http://localhost:3000/api/health says the database is ok.
Then it deletes its own two test rows, so no test data is left behind.

It needs only Python (no extra packages): it reaches the broker and the database through
"docker compose exec", so no database port has to be opened. It sends as the Acme test device,
so Acme must be the enabled device (the default in mappings/bindings/site1.ttl).

Sources:
  - mosquitto_pub (sends one MQTT message): https://mosquitto.org/man/mosquitto_pub-1.html
  - Grafana health endpoint (GET /api/health):
      https://grafana.com/docs/grafana/v13.2/developer-resources/api-reference/http-api/api-legacy/other/
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

V01 = Path(__file__).resolve().parents[1]
TOPIC = "raw/acme/acme_hvac_0001/telemetry"
WAIT_S = 15                      # the historian writes at least once a second; allow for start-up


def compose(*args: str) -> str:
    """Run a command inside a Compose service; return its output (raises on failure)."""
    out = subprocess.run(["docker", "compose", "exec", "-T", *args], cwd=V01,
                         capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or out.stdout.strip())
    return out.stdout.strip()


def publish(topic: str, payload: dict) -> None:
    compose("mosquitto", "mosquitto_pub", "-q", "1", "-t", topic, "-m", json.dumps(payload))


def sql(query: str) -> str:
    return compose("timescaledb", "psql", "-U", "dtteo_owner", "-d", "dtteo", "-tA", "-c", query)


def wait_for(query: str) -> str:
    deadline = time.monotonic() + WAIT_S
    while time.monotonic() < deadline:
        result = sql(query)
        if result:
            return result
        time.sleep(1)
    return ""


def main() -> int:
    results: list[tuple[str, bool, str]] = []
    def check(name: str, ok: bool, detail: str) -> None:
        results.append((name, ok, detail))
        print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}")

    # 1. Migrations
    expected = len(list((V01 / "storage" / "migrations").glob("*.sql")))
    try:
        applied = int(sql("SELECT count(*) FROM schema_migrations"))
        check("migrations", applied == expected, f"{applied} of {expected} applied"
              + ("" if applied == expected else "  -> docker compose logs migrate"))
    except Exception as e:                       # database not running at all
        check("database", False, f"can't run SQL ({e})  -> docker compose up -d")
        return 1

    # 2 + 3. One message: a known field (-> readings) and an unknown one (-> quarantine).
    ts_ms = int(time.time() * 1000)              # unique sensor time = how we find our reading
    marker = f"smoke_test_{ts_ms}"               # unique unknown field = how we find our quarantine row
    try:
        publish(TOPIC, {"deviceId": "ACME-HVAC-0001", "ts": ts_ms, "tempF": 70.0, marker: 1})
    except Exception as e:
        check("broker", False, f"can't publish ({e})")
        return 1
    iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ts_ms // 1000)) + f".{ts_ms % 1000:03d}Z"
    sensor_time = f"TIMESTAMPTZ '{iso}'"         # exact, as the gateway stores it (milliseconds, UTC)
    reading = wait_for(f"""
        SELECT r.value_num || ' ' || r.quality FROM readings r JOIN series s USING (series_id)
        WHERE s.point_id = 'unit1.zone_air_temp' AND r.sensor_time = {sensor_time}""")
    check("reading path (gateway -> historian -> readings)", reading.startswith("21.1111 GOOD"),
          f"stored as {reading}" if reading else
          f"nothing after {WAIT_S}s  -> docker compose logs gateway historian (is Acme the enabled device?)")
    quarantined = wait_for(f"SELECT stage FROM quarantine WHERE field = '{marker}'")
    check("quarantine path", quarantined == "map",
          f"stored with stage '{quarantined}'" if quarantined else f"nothing after {WAIT_S}s")

    # 4. Summaries answer (they may be empty; they must not error).
    for view in ("summary_1h", "total_1h"):
        try:
            n = sql(f"SELECT count(*) FROM {view}")
            check(f"summary {view}", True, f"{n} rows")
        except Exception as e:
            check(f"summary {view}", False, str(e).splitlines()[0])

    # 5. Grafana
    try:
        with urllib.request.urlopen("http://localhost:3000/api/health", timeout=5) as r:
            health = json.loads(r.read())
        check("grafana", health.get("database") == "ok", f"version {health.get('version')}, database {health.get('database')}")
    except Exception as e:
        check("grafana", False, f"not reachable ({e})  -> docker compose logs grafana")

    # Clean up our two test rows (as the owner; the historian's own login can't delete).
    sql(f"""DELETE FROM readings WHERE sensor_time = {sensor_time} AND series_id =
              (SELECT series_id FROM series WHERE site = 'site1' AND point_id = 'unit1.zone_air_temp');
            DELETE FROM quarantine WHERE field = '{marker}';""")

    failed = [name for name, ok, _ in results if not ok]
    print(f"\n{'ALL PASSED' if not failed else 'FAILED: ' + ', '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
