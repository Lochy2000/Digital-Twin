"""
Store: messages in, database rows out. No MQTT in here (service.py does that), so it can be
tested on its own, like the gateway's pipeline.py.

    Historian (interface)          write(messages) -> Result      read(site, point, start, end)
    PostgresHistorian              the one implementation now: plain SQL through psycopg 3

What write() does with one batch, in ONE transaction:
    canonical message (dt/v1/telemetry/...)   -> readings      (duplicate site+point+time skipped)
    quarantine message (dt/v1/quarantine/...) -> quarantine
    anything it can't store                   -> quarantine, stage "store", with the reason
If the database refuses the whole batch because of one bad row, it retries row by row so that
one bad message can't block the rest ("poison message").
If the database is DOWN, write() raises StoreUnavailable and stores nothing: the service then
keeps the batch, doesn't acknowledge it, and tries again (ADR-002 section 7).

Sources:
  - The interface (VOLTTRON historian pattern), table design, ON CONFLICT DO NOTHING:
      decisions/ADR-002-database-layout.md, sections 3, 4, 7
  - psycopg 3: executemany() uses pipeline mode (few network round trips):
      https://psycopg.org/psycopg3/docs/advanced/pipeline.html
  - Message shapes: contracts/canonical_message.schema.json, quarantine_message.schema.json
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, Protocol

import psycopg
from psycopg.types.json import Jsonb

log = logging.getLogger("historian")

CANONICAL_PREFIX = "dt/v1/telemetry/"
QUARANTINE_PREFIX = "dt/v1/quarantine/"


class StoreUnavailable(Exception):
    """The database can't be reached right now. Nothing from the batch was stored."""


@dataclass(frozen=True)
class Message:
    topic: str
    payload: bytes


@dataclass
class Result:
    readings: int = 0            # new reading rows
    duplicates: int = 0          # skipped: same site + point + sensor_time already stored
    quarantined: int = 0         # rows written to the quarantine table (from the gateway or by us)
    problems: list[str] = field(default_factory=list)   # why something went to quarantine here


class Historian(Protocol):
    def write(self, messages: list[Message]) -> Result: ...
    def read(self, site: str, point: str, start: datetime, end: datetime) -> list[dict]: ...


# --- Turning one message into one row (no database needed) -------------------------------

class Unstorable(Exception):
    """This message can't become a row; it goes to quarantine with this reason."""


def _time(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def value_columns(value) -> tuple:
    """(value_num, value_text, value_bool): exactly one filled. bool first: True is an int in Python."""
    if isinstance(value, bool):
        return None, None, value
    if isinstance(value, (int, float)):
        return float(value), None, None
    if isinstance(value, str):
        return None, value, None
    raise Unstorable(f"value {value!r} is not a number, word or true/false")


def reading_row(msg: dict, series_id: int) -> tuple:
    """A canonical message (already checked against the contract) -> readings row."""
    num, text, flag = value_columns(msg["value"])
    return (series_id, _time(msg["sensor_time"]), _time(msg["ingest_time"]), num, text, flag,
            msg["quality"], Jsonb(msg["qc"]) if "qc" in msg else None, msg["time_source"],
            msg.get("source"), msg["v"])


def quarantine_row(q: dict) -> tuple:
    """A quarantine message from the gateway -> quarantine row."""
    return (_time(q["ingest_time"]), q["site"], q["stage"], q["reason"], q.get("topic"),
            q.get("source"), q.get("device"), q.get("field"),
            Jsonb(q["value"]) if "value" in q else None, q["raw"], q["v"])


def store_problem_row(m: Message, reason: str, site: str, now: datetime) -> tuple:
    """Something WE couldn't store -> quarantine row, stage "store", original kept for replay."""
    return (now, site, "store", reason, m.topic, None, None, None, None,
            m.payload.decode("utf-8", errors="replace"), 0)


# --- PostgreSQL ----------------------------------------------------------------------------

_INSERT_READING = """
INSERT INTO readings (series_id, sensor_time, ingest_time, value_num, value_text, value_bool,
                      quality, qc, time_source, source, msg_version)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (series_id, sensor_time) DO NOTHING"""

_INSERT_QUARANTINE = """
INSERT INTO quarantine (ingest_time, site, stage, reason, topic, source, device, field, value,
                        raw, msg_version)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""

_UPSERT_SERIES = """
INSERT INTO series (site, point_id, unit, brick_class, kind) VALUES (%s, %s, %s, %s, %s)
ON CONFLICT (site, point_id) DO UPDATE
   SET unit = EXCLUDED.unit, brick_class = EXCLUDED.brick_class, kind = EXCLUDED.kind"""

_TOUCH_SERIES = """
UPDATE series SET first_seen = COALESCE(first_seen, %(t)s), last_seen = GREATEST(last_seen, %(t)s)
WHERE series_id = %(id)s"""


class PostgresHistorian:
    def __init__(self, dsn: str, site: str, validate=None, clock=None):
        """
        dsn       e.g. postgresql://historian:pw@timescaledb:5432/dtteo
        site      the default site for rows about messages we couldn't read at all
        validate  function(message dict, kind) -> list of error strings ([] = valid);
                  kind is "canonical" or "quarantine". Normally the JSON Schema contracts.
        """
        self.dsn, self.site = dsn, site
        self.validate = validate or (lambda msg, kind: [])
        self.clock = clock or (lambda: datetime.now().astimezone())
        self.conn: psycopg.Connection | None = None
        self.series: dict[tuple[str, str], int] = {}       # (site, point) -> series_id

    # Connection --------------------------------------------------------------------------
    def connect(self) -> None:
        try:
            if self.conn is None or self.conn.closed:
                self.conn = psycopg.connect(self.dsn, connect_timeout=5)
                self._load_series()
        except psycopg.OperationalError as e:
            self.conn = None
            raise StoreUnavailable(str(e).strip()) from e

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()

    def _load_series(self) -> None:
        with self.conn.cursor() as cur:
            cur.execute("SELECT site, point_id, series_id FROM series")
            self.series = {(s, p): i for s, p, i in cur.fetchall()}
        self.conn.commit()

    # Series: copied from the asset model at start-up (ADR-002 section 3.2) ---------------
    def sync_series(self, site: str, points: Iterable) -> int:
        """points: gateway.mapper.PointInfo items (point_id, unit, brick_class, kind)."""
        self.connect()
        rows = [(site, p.point_id, p.unit, p.brick_class, p.kind) for p in points]
        try:
            with self.conn.transaction(), self.conn.cursor() as cur:
                cur.executemany(_UPSERT_SERIES, rows)
        except psycopg.OperationalError as e:
            self.conn = None
            raise StoreUnavailable(str(e).strip()) from e
        self._load_series()
        return len(rows)

    # Writing -----------------------------------------------------------------------------
    def write(self, messages: list[Message]) -> Result:
        self.connect()
        result, readings, quarantine, touched = Result(), [], [], {}
        now = self.clock()
        for m in messages:
            self._sort(m, result, readings, quarantine, touched, now)
        try:
            try:
                self._insert(readings, quarantine, touched, result)
            except (psycopg.IntegrityError, psycopg.DataError) as e:
                # One bad row spoils the whole transaction. Retry one by one (the batch above
                # was rolled back, so nothing is stored twice).
                log.warning(f"batch_refused error={type(e).__name__} retrying_one_by_one={len(messages)}")
                result = self._write_one_by_one(messages, now)
        except psycopg.OperationalError as e:
            self.conn = None
            raise StoreUnavailable(str(e).strip()) from e
        return result

    def _sort(self, m, result, readings, quarantine, touched, now) -> None:
        """Decide where one message goes; anything unstorable becomes a "store" quarantine row."""
        try:
            msg = json.loads(m.payload)
            if not isinstance(msg, dict):
                raise Unstorable("not a JSON object")
            if m.topic.startswith(QUARANTINE_PREFIX):
                self._check(msg, "quarantine")
                quarantine.append(quarantine_row(msg))
            elif m.topic.startswith(CANONICAL_PREFIX):
                self._check(msg, "canonical")
                series_id = self.series.get((msg["site"], msg["point"]))
                if series_id is None:
                    raise Unstorable(f"no series for {msg['site']}/{msg['point']} (is the point in the "
                                     "asset model? restart the historian after changing it)")
                readings.append(reading_row(msg, series_id))
                t = _time(msg["sensor_time"])
                touched[series_id] = max(t, touched.get(series_id, t))
            else:
                raise Unstorable(f"not a topic the historian stores: {m.topic}")
        except (ValueError, Unstorable) as e:          # json errors are ValueErrors
            reason = str(e) if isinstance(e, Unstorable) else f"not valid JSON: {e}"
            result.problems.append(reason)
            quarantine.append(store_problem_row(m, reason, self.site, now))

    def _check(self, msg: dict, kind: str) -> None:
        errors = self.validate(msg, kind)
        if errors:
            raise Unstorable(f"not a valid {kind} message: " + "; ".join(errors[:3]))

    def _insert(self, readings, quarantine, touched, result) -> None:
        with self.conn.transaction(), self.conn.cursor() as cur:
            new = 0
            if readings:
                cur.executemany(_INSERT_READING, readings)
                new = cur.rowcount                    # psycopg 3: the total over all rows, so
                                                      # len(readings) - new = duplicates skipped
            if quarantine:
                cur.executemany(_INSERT_QUARANTINE, quarantine)
            if touched:
                cur.executemany(_TOUCH_SERIES, [{"id": i, "t": t} for i, t in touched.items()])
        result.readings += new
        result.duplicates += len(readings) - new
        result.quarantined += len(quarantine)

    def _write_one_by_one(self, messages: list[Message], now) -> Result:
        total = Result()
        for m in messages:
            r = Result()
            readings, quarantine, touched = [], [], {}
            self._sort(m, r, readings, quarantine, touched, now)
            try:
                self._insert(readings, quarantine, touched, r)
            except (psycopg.IntegrityError, psycopg.DataError) as e:
                reason = f"database refused it: {str(e).strip().splitlines()[0]}"
                r = Result(problems=[reason])
                self._insert([], [store_problem_row(m, reason, self.site, now)], {}, r)
            total.readings += r.readings
            total.duplicates += r.duplicates
            total.quarantined += r.quarantined
            total.problems += r.problems
        return total

    # Reading (for tests and simple tools; dashboards query the database directly) ---------
    def read(self, site: str, point: str, start: datetime, end: datetime) -> list[dict]:
        self.connect()
        with self.conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute("""
                SELECT r.sensor_time, r.ingest_time, COALESCE(to_jsonb(r.value_num), to_jsonb(r.value_text),
                       to_jsonb(r.value_bool)) AS value, r.quality, r.qc, r.time_source, r.source
                FROM readings r JOIN series s USING (series_id)
                WHERE s.site = %s AND s.point_id = %s AND r.sensor_time >= %s AND r.sensor_time < %s
                ORDER BY r.sensor_time""", (site, point, start, end))
            rows = cur.fetchall()
        self.conn.commit()
        return rows
