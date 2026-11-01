"""
E1: does the pipeline handle bad data as RR 1 section 5 requires?

Part A (gateway logic, in-process, deterministic): sensor faults injected into 3 days of
synthetic zone temperature, plus single bad messages (clocks, formats). Records the quality
or quarantine stage the gateway gives each one.
Part B (whole pipeline through the broker into the database): duplicates, out-of-order,
missing fields and a NaN value, checking what ends up stored.

    python experiments/e1_data_quality.py
"""
from __future__ import annotations

import json
import math
import random
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "services" / "ingestion-gateway")]

import harness as h  # noqa: E402
from gateway.mapper import Mapper  # noqa: E402
from gateway.pipeline import Pipeline  # noqa: E402

random.seed(42)
NOW = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
ACME, TASMOTA = "raw/acme/acme_hvac_0001/telemetry", "raw/tasmota/tasmota_zone1/tele/SENSOR"
acme_pipe = Pipeline(Mapper.from_folder(h.V01), site="site1")
tasmota_pipe = Pipeline(Mapper.from_folder(h.V01, enabled={"acme_hvac_0001": False, "tasmota_zone1": True}), site="site1")


def f(c: float) -> float:
    return round(c * 9 / 5 + 32, 2)


def outcome(outs, point="unit1.zone_air_temp") -> tuple[str, str]:
    """(result, detail) for the zone temperature: GOOD/SUSPECT/BAD, or QUARANTINE:<stage>, or NOT STORED."""
    for o in outs:
        b = o.payload
        if b.get("point") == point:
            tests = ",".join(q["test"] for q in b.get("qc", []))
            return b["quality"], f"{tests} time_source={b['time_source']} value={b['value']}"
    for o in outs:
        if o.topic.startswith("dt/v1/quarantine"):
            return f"QUARANTINE:{o.payload['stage']}", o.payload.get("reason", "")[:90]
    return "NOT STORED", ""


# --- Part A1: sensor faults on a realistic series -----------------------------------------------
def series_with_faults():
    """3 days at 1 sample a minute: 21 C +/- 2 C daily cycle + 0.1 C noise, with labelled faults."""
    n, t0 = 3 * 1440, NOW - timedelta(days=3)
    clean = [21 + 2 * math.sin(2 * math.pi * i / 1440) + random.gauss(0, 0.1) for i in range(n)]
    values, label = clean[:], ["clean"] * n
    def put(i, v, name):
        values[i], label[i] = v, name
    for i in random.sample(range(100, 1400), 20):                       # spike that stays inside 5..35 C
        put(i, clean[i] + 6, "spike (+6 C, inside expected range)")
    for i in random.sample(range(1500, 2800), 10):                      # spike that leaves 5..35 C
        put(i, clean[i] + 20, "spike (+20 C, outside expected range)")
    for start in (3000, 3400, 3800):                                    # stuck sensor: 2 h at one value
        for i in range(start, start + 120):
            put(i, round(clean[start], 1), "flat line (stuck 2 h)")
    for start in (2900, 3600):                                          # step change: +7 C for 1 h
        for i in range(start, start + 60):
            put(i, clean[i] + 7, "step / rate of change (+7 C for 1 h)")
    for i in range(2 * 1440, 3 * 1440):                                 # drift: +3 C over the last day
        if label[i] == "clean":
            put(i, clean[i] + 3 * (i - 2 * 1440) / 1440, "slow drift (+3 C over 1 day)")
    for i in random.sample(range(100, 2800), 10):                       # dropout read as 0
        if label[i] == "clean":
            put(i, 0.0, "dropout read as 0.0 C")
    return [(t0 + timedelta(minutes=i), values[i], label[i], clean[i]) for i in range(n)]


def part_a1():
    rows = []
    for t, v, lab, clean in series_with_faults():
        ts = int(t.timestamp() * 1000)
        outs = acme_pipe.process(ACME, json.dumps({"ts": ts, "tempF": f(v), "op_state": 2}).encode(), now=t + timedelta(seconds=1))
        q, detail = outcome(outs)
        rows.append({"device": "acme", "sensor_time": t.isoformat(), "value_c": round(v, 3), "clean_c": round(clean, 3),
                     "label": lab, "quality": q, "qc": detail.split(" ")[0] if q != "GOOD" else ""})
    # The real Tasmota probe format, with its datasheet range (-55..125 C) and its power-on value.
    for lab, v in [("DS18B20 power-on reset value (85 C)", 85.0), ("outside sensor range (130 C)", 130.0),
                   ("clean (Tasmota)", 21.4)]:
        for k in range(10):
            t = NOW - timedelta(minutes=k)
            local = t.astimezone(timezone(timedelta(0))).replace(tzinfo=None)   # 1 Nov 2026: London = UTC
            payload = {"Time": local.isoformat(timespec="seconds"), "DS18B20": {"Id": "00000566CC39", "Temperature": v}, "TempUnit": "C"}
            q, detail = outcome(tasmota_pipe.process(TASMOTA, json.dumps(payload).encode(), now=t + timedelta(seconds=1)))
            rows.append({"device": "tasmota", "sensor_time": t.isoformat(), "value_c": v, "clean_c": "",
                         "label": lab, "quality": q, "qc": detail.split(" ")[0] if q != "GOOD" else ""})
    h.write_csv("e1_sensor_faults_samples.csv", rows)
    summary = {}
    for r in rows:
        s = summary.setdefault(r["label"], {"fault": r["label"], "samples": 0, "GOOD": 0, "SUSPECT": 0, "BAD": 0, "tests": set()})
        s["samples"] += 1
        s[r["quality"]] = s.get(r["quality"], 0) + 1
        if r["qc"]:
            s["tests"].add(r["qc"])
    out = []
    for s in summary.values():
        flagged = s["SUSPECT"] + s["BAD"]
        is_clean = s["fault"].startswith("clean")
        out.append({"fault": s["fault"], "samples": s["samples"], "flagged": flagged,
                    "flagged_pct": round(100 * flagged / s["samples"], 1), "GOOD": s["GOOD"], "SUSPECT": s["SUSPECT"],
                    "BAD": s["BAD"], "by_test": " ".join(sorted(s["tests"])) or "-",
                    "kind": "false alarms on clean data" if is_clean else "detection"})
    h.write_csv("e1_sensor_faults.csv", out)
    return out


# --- Part A2: single bad messages -------------------------------------------------------------
def part_a2():
    ts = int(NOW.timestamp() * 1000)
    later = NOW + timedelta(seconds=1)
    A = lambda body: acme_pipe.process(ACME, body if isinstance(body, bytes) else json.dumps(body).encode(), now=later)
    T = lambda time_text: tasmota_pipe.process(TASMOTA, json.dumps({"Time": time_text, "DS18B20": {"Id": "x", "Temperature": 21.0}, "TempUnit": "C"}).encode(),
                                               now=datetime(2026, 10, 25, 2, 0, tzinfo=timezone.utc))
    cases = [
        # (group, case, expected per RR 1 / QARTOD, outs)
        ("time", "no timestamp in message", "recorded as unknown, not substituted (RR 1 §5)", A({"tempF": 70.0})),
        ("time", "clock 1 day ahead", "not GOOD", A({"ts": ts + 86_400_000, "tempF": 70.0})),
        ("time", "clock 30 min ahead", "not GOOD", A({"ts": ts + 1_800_000, "tempF": 70.0})),
        ("time", "clock reset to 1970 (power loss)", "not GOOD (RR 1: flag readings after power loss)", A({"ts": 0, "tempF": 70.0})),
        ("time", "clock 2 h behind", "not GOOD (wrong time looks like a fault, RR 1)", A({"ts": ts - 7_200_000, "tempF": 70.0})),
        ("time", "Tasmota local time 01:30 on 25 Oct (clocks go back: happens twice)", "flagged as ambiguous",
         T("2026-10-25T01:30:00")),
        ("format", "not JSON", "quarantined", A(b"tempF=70")),
        ("format", "empty payload", "quarantined", A(b"")),
        ("format", "JSON array instead of object", "quarantined", A([1, 2])),
        ("format", "timestamp is text", "quarantined", A({"ts": "yesterday", "tempF": 70.0})),
        ("format", "temperature is text", "quarantined", A({"ts": ts, "tempF": "hot"})),
        ("format", "temperature is a number in quotes", "quarantined or converted", A({"ts": ts, "tempF": "70.5"})),
        ("format", "temperature is null", "quarantined", A({"ts": ts, "tempF": None})),
        ("format", "temperature is true", "quarantined", A({"ts": ts, "tempF": True})),
        ("format", "temperature is NaN", "quarantined or BAD", A(b'{"ts": %d, "tempF": NaN}' % ts)),
        ("format", "temperature is Infinity", "quarantined or BAD", A(b'{"ts": %d, "tempF": Infinity}' % ts)),
        ("format", "unknown mode code (op_state 9)", "quarantined", acme_pipe.process(ACME, json.dumps({"ts": ts, "op_state": 9}).encode(), now=later)),
        ("format", "field nobody mapped", "quarantined", A({"ts": ts, "fanRPM": 900})),
        ("format", "device nobody bound", "quarantined",
         acme_pipe.process("raw/acme/acme_hvac_9999/telemetry", json.dumps({"ts": ts, "tempF": 70.0}).encode(), now=later)),
        ("format", "vendor nobody knows", "quarantined",
         acme_pipe.process("raw/zeta/z1/telemetry", json.dumps({"ts": ts, "tempF": 70.0}).encode(), now=later)),
    ]
    rows = []
    for group, case, expected, outs in cases:
        point = "unit1.mode_status" if "op_state" in case else "unit1.zone_air_temp"
        q, detail = outcome(outs, point)
        rows.append({"group": group, "case": case, "expected": expected, "observed": q, "detail": detail})
    h.write_csv("e1_messages.csv", rows)
    return rows


# --- Part B: through the broker into the database ------------------------------------------------
def part_b():
    h.clear_tables()
    stack = h.Stack("e1").up()
    dev = h.Device()
    base = h.now_ms() - 3_600_000
    rows = []

    def count(t0, t1):
        return len(h.stored(t0, t1))

    # B1 duplicates: 200 messages, then the same 200 again (as a QoS 1 redelivery would)
    t0 = base
    for i in range(200):
        dev.send(t0 + i * 1000)
    for i in range(200):
        dev.send(t0 + i * 1000)
    dev.wait_published()
    got = h.wait_stored(10**9, t0, t0 + 199_000, timeout=6)
    rows.append({"case": "200 messages sent twice", "expected": "200 rows", "observed": f"{len(got)} rows",
                 "pass": len(got) == 200})

    # B2 out of order: 200 messages in shuffled order
    t0 = base + 600_000
    order = list(range(200))
    random.shuffle(order)
    for i in order:
        dev.send(t0 + i * 1000, temp_f=60 + i / 10)
    dev.wait_published()
    got = h.wait_stored(200, t0, t0 + 199_000, timeout=10)
    vals = h.sql("""SELECT r.value_num FROM readings r JOIN series s USING (series_id) WHERE s.point_id=%s
                    AND r.sensor_time BETWEEN to_timestamp(%s/1000.0) AND to_timestamp(%s/1000.0) ORDER BY r.sensor_time""",
                 (h.TEMP_POINT, t0, t0 + 199_000))
    expected_vals = [round((60 + i / 10 - 32) * 5 / 9, 4) for i in range(200)]
    in_order = [round(v[0], 4) for v in vals] == expected_vals
    rows.append({"case": "200 messages in shuffled order", "expected": "200 rows, each at its own sensor time",
                 "observed": f"{len(got)} rows, values match their times: {in_order}", "pass": len(got) == 200 and in_order})

    # B3 missing: every other message has no tempF
    t0 = base + 1_200_000
    for i in range(100):
        body = {"deviceId": "ACME-HVAC-0001", "ts": t0 + i * 1000, "op_state": 2}
        if i % 2 == 0:
            body["tempF"] = 70.0
        dev.send(0, raw=json.dumps(body).encode())
    dev.wait_published()
    got = h.wait_stored(50, t0, t0 + 99_000, timeout=8)
    zero_rows = h.sql("""SELECT count(*) FROM readings r JOIN series s USING (series_id) WHERE s.point_id=%s
                         AND r.sensor_time BETWEEN to_timestamp(%s/1000.0) AND to_timestamp(%s/1000.0) AND r.value_num = 0""",
                      (h.TEMP_POINT, t0, t0 + 99_000))[0][0]
    rows.append({"case": "100 messages, 50 without a temperature", "expected": "50 rows, no zeros",
                 "observed": f"{len(got)} rows, {zero_rows} zeros", "pass": len(got) == 50 and zero_rows == 0})
    has_completeness = h.sql("""SELECT count(*) FROM information_schema.tables
                                WHERE table_name ILIKE '%complete%' OR table_name ILIKE '%gap%'""")[0][0]
    rows.append({"case": "completeness reported per point", "expected": "a completeness or gap view exists",
                 "observed": "none found in the database" if not has_completeness else "found", "pass": bool(has_completeness)})

    # B4 NaN and Infinity end to end
    t0 = base + 1_800_000
    dev.send(0, raw=b'{"ts": %d, "tempF": NaN, "op_state": 2}' % t0)
    dev.send(0, raw=b'{"ts": %d, "tempF": Infinity, "op_state": 2}' % (t0 + 1000))
    for i in range(2, 60):                                   # 58 normal readings in the same minute
        dev.send(t0 + i * 1000, temp_f=70.0)
    dev.wait_published()
    time.sleep(3)
    stored = h.sql("""SELECT r.value_num::text, r.quality FROM readings r JOIN series s USING (series_id) WHERE s.point_id=%s
                      AND r.sensor_time BETWEEN to_timestamp(%s/1000.0) AND to_timestamp(%s/1000.0) ORDER BY r.sensor_time""",
                   (h.TEMP_POINT, t0, t0 + 1000))
    rows.append({"case": "NaN and Infinity temperatures", "expected": "quarantined, or stored as BAD",
                 "observed": "; ".join(f"stored {v} {qq}" for v, qq in stored) or "not stored",
                 "pass": all(qq == "BAD" for _, qq in stored)})
    # What that does to the hourly summary (same filter as summary_1h: everything except BAD)
    mean, mx, n = h.sql("""SELECT avg(value_num)::text, max(value_num)::text, count(*) FROM readings r JOIN series s USING (series_id)
                         WHERE s.point_id=%s AND quality <> 'BAD' AND value_num IS NOT NULL
                         AND sensor_time BETWEEN to_timestamp(%s/1000.0) AND to_timestamp(%s/1000.0)""",
                      (h.TEMP_POINT, t0, t0 + 59_000))[0]
    rows.append({"case": "summary over those 60 readings (58 normal, NaN, Infinity)", "expected": "mean of the 58 normal readings (21.1)",
                 "observed": f"mean {mean}, max {mx} over {n} readings", "pass": mean not in ("NaN", "Infinity")})
    alive = all(p.poll() is None for p in stack.procs.values())
    rows.append({"case": "services still running after all bad input", "expected": "yes", "observed": "yes" if alive else "no", "pass": alive})
    dev.close()
    stack.down()
    h.write_csv("e1_storage.csv", rows)
    return rows


if __name__ == "__main__":
    print(h.stamp(), "E1 part A1")
    for r in part_a1():
        print(f"  {r['fault']:<42} {r['flagged']:>5}/{r['samples']:<5} {r['flagged_pct']:>5}%  {r['by_test']}")
    print("E1 part A2")
    for r in part_a2():
        print(f"  {r['case']:<62} {r['observed']:<20} {r['detail'][:70]}")
    print("E1 part B")
    for r in part_b():
        print(f"  {'PASS' if r['pass'] else 'FAIL'}  {r['case']:<45} {r['observed']}")
