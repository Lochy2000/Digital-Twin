"""
Replay a dt-edge recording through the gateway (v0.2 step C).

    python replay_run.py <readings.csv> [more.csv ...]              offline: summary, no Docker needed
    python replay_run.py <readings.csv> ... --publish                send to the dev stack's broker

Input: one or more CSVs of one dt-edge run (Recorded runs page -> download). A run saved in parts
(e.g. the matrix cool-down, 3 files) is passed as several files; rows are sorted by time.
Both of dt-edge's downloads work, and the format is detected from the header:
  - "All readings" (readings.csv): one row per reading: time, t_s, point_id, label, value, unit, quality, qc
  - "Excel CSV": one row per second, one column per sensor, headed "Label (unit) [point_id]".
    Columns are matched by the [point_id], so their order doesn't matter. A blank cell = that
    sensor had no reading that second (skipped). This format has no quality column, so every
    value counts as GOOD from the rig; the gateway's own checks still run.

Each row becomes the message dt-edge itself would send (dt-edge app/record.py), grouped one
message per moment (all readings with the same time), on raw/dtedge/digitwin_pi/telemetry.

OFFLINE (default) runs the gateway's own pipeline in this process, with the gateway's model,
and prints: readings per point and quality, quarantine reasons, and any output that breaks the
contract. Each message is treated as arriving 0.5 s after it was measured, so the age checks
judge the data, not the replay. Needs:  pip install -e ../common -r ../gateway/requirements.txt

--publish sends to the dev broker (localhost:1883) as the Pi would (login digitwin_pi, password
MQTT_DEVICE_PASSWORD from dev/.env). Times are moved to "now" (same spacing), because the
recording's times are old (or wrong, if the Pi's clock was off) and the gateway would flag them
late. They end at "now", so a run longer than 6 h has its oldest readings flagged late_arrival:
use --speed 1 (real time) for those. --keep-times sends the original times. --speed N plays N times faster (default: as fast as
the broker takes it). Watch:  docker compose logs -f gateway historian

What a CSV can't carry: types. A value is read as a number where it is one, empty = no value,
and the plug's on/off (written as 1/0) is turned back into true/false.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEV = Path(__file__).resolve().parent
V02 = DEV.parent
TOPIC = "raw/dtedge/digitwin_pi/telemetry"
BOOLEAN_POINTS = (".on",)               # dt-edge writes booleans to its CSV as 1 / 0


def value_of(point_id: str, text: str):
    if text == "":
        return None
    if point_id.endswith(BOOLEAN_POINTS):
        return text.strip() in ("1", "True", "true")
    try:
        number = float(text)
    except ValueError:
        return text
    return int(number) if number.is_integer() and "." not in text else number


# Unit text in the Excel CSV's headers -> QUDT id (as in the readings.csv "unit" column).
HEADER_UNITS = {"degC": "DEG_C", "%RH": "PERCENT_RH", "hPa": "HectoPA", "W": "W", "kWh": "KiloW-HR"}
WIDE_COLUMN = re.compile(r"^(?P<label>.*?)\s*(\((?P<unit>[^()]*)\))?\s*\[(?P<point>[^\[\]]+)\]$")


def message(t: datetime, point_id: str, value, unit, quality="GOOD", qc=None) -> dict:
    """One reading, shaped as dt-edge sends it (dt-edge app/record.py, to_message())."""
    return {"v": 2, "site": "rig1", "point_id": point_id, "value": value, "unit": unit or None,
            "sensor_time": t.isoformat(), "quality": quality or "GOOD", "qc": qc or None,
            "time_source": "device", "source": f"dtedge:{point_id.split('.')[0]}"}


def when(text: str) -> datetime:
    t = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def load(files: list[Path]) -> list[tuple[datetime, list[dict]]]:
    """CSV rows -> [(time, [dt-edge messages measured at that time])], oldest first."""
    moments: dict[datetime, list[dict]] = defaultdict(list)
    for f in files:
        with open(f, newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            header = reader.fieldnames or []
            if "point_id" in header:                                   # "All readings" (readings.csv)
                for row in reader:
                    moments[when(row["time"])].append(message(
                        when(row["time"]), row["point_id"], value_of(row["point_id"], row["value"]), row.get("unit"),
                        row.get("quality"), [q for q in (row.get("qc") or "").split(";") if q]))
                continue
            columns = {c: WIDE_COLUMN.match(c) for c in header if c not in ("time", "t_s")}
            if not header or "time" not in header or not all(columns.values()):
                bad = [c for c, m in columns.items() if not m]
                raise SystemExit(f"{f}: not a dt-edge CSV (expected a point_id column, or columns "
                                 f"headed 'Label (unit) [point_id]'; can't read {bad[:3] or header[:3]})")
            for row in reader:                                          # "Excel CSV": one row per second
                t = when(row["time"])
                for col, m in columns.items():
                    text = (row.get(col) or "").strip()
                    if text == "":
                        continue                                        # no reading from that sensor this second
                    point = m["point"]
                    moments[t].append(message(t, point, value_of(point, text),
                                              HEADER_UNITS.get((m["unit"] or "").strip(), m["unit"])))
        print(f"read {f.name}")
    return sorted(moments.items())


def offline(moments) -> int:
    logging.getLogger("gateway").setLevel(logging.ERROR)     # the summary below replaces the per-message log
    sys.path.insert(0, str(V02 / "gateway"))
    from jsonschema import Draft202012Validator, FormatChecker
    from dtteo_common.contracts import schema_path
    from dtteo_common.mapper import Mapper
    from gateway.pipeline import Pipeline

    pipeline = Pipeline(Mapper.from_folder(V02 / "gateway" / "model"), site="site1")
    schema = Draft202012Validator(json.loads(schema_path("canonical").read_text()), format_checker=FormatChecker())
    per_point: dict[str, Counter] = defaultdict(Counter)
    flags, quarantined, invalid = Counter(), Counter(), 0
    for t, msgs in moments:
        for o in pipeline.process(TOPIC, json.dumps(msgs).encode(), t + timedelta(seconds=0.5)):
            p = o.payload
            if o.topic.startswith("dt/v1/telemetry/"):
                per_point[p["point"]][p["quality"]] += 1
                for c in p.get("qc", []):
                    flags[(p["point"], c["test"])] += 1
                invalid += bool(list(schema.iter_errors(p)))
            else:
                quarantined[(p.get("field"), p["reason"][:90])] += 1

    n = sum(len(m) for _, m in moments)
    print(f"{n} readings in {len(moments)} moments, {moments[0][0]:%Y-%m-%d %H:%M:%S} to {moments[-1][0]:%H:%M:%S} UTC "
          f"({(moments[-1][0] - moments[0][0]).total_seconds() / 3600:.2f} h)\n")
    print(f"{'point':28}{'GOOD':>9}{'SUSPECT':>9}{'BAD':>7}")
    for point in sorted(per_point):
        c = per_point[point]
        print(f"{point:28}{c['GOOD']:>9}{c['SUSPECT']:>9}{c['BAD']:>7}")
    if flags:
        print("\nwhy readings were flagged (point, check: count):")
        for (point, test), k in sorted(flags.items()):
            print(f"  {point}, {test}: {k}")
    if quarantined:
        print("\nquarantined (field: reason: count):")
        for (field, reason), k in sorted(quarantined.items(), key=lambda x: -x[1]):
            print(f"  {field}: {reason}: {k}")
    stored = sum(sum(c.values()) for c in per_point.values())
    print(f"\n{stored} readings would be stored, {sum(quarantined.values())} quarantined, "
          f"{invalid} broke the contract")
    return 1 if invalid else 0


def publish(moments, keep_times: bool, speed: float) -> int:
    import paho.mqtt.client as mqtt

    password = next(line.split("=", 1)[1].strip() for line in (DEV / ".env").read_text().splitlines()
                    if line.startswith("MQTT_DEVICE_PASSWORD="))
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="replay_digitwin_pi", protocol=mqtt.MQTTv5)
    client.username_pw_set("digitwin_pi", password)
    client.connect("localhost", 1883)
    client.loop_start()
    shift = timedelta(0) if keep_times else datetime.now(timezone.utc) - moments[-1][0]
    start, first = time.monotonic(), moments[0][0]
    sent = 0
    for t, msgs in moments:
        if speed > 0:
            wait = (t - first).total_seconds() / speed - (time.monotonic() - start)
            if wait > 0:
                time.sleep(wait)
        for m in msgs:
            m["sensor_time"] = (t + shift).isoformat()
        client.publish(TOPIC, json.dumps(msgs), qos=1).wait_for_publish(timeout=10)
        sent += len(msgs)
        if sent % 5000 < len(msgs):
            print(f"  {sent} readings sent")
    client.loop_stop()
    client.disconnect()
    print(f"{sent} readings sent in {len(moments)} messages to {TOPIC}"
          + ("" if keep_times else f" (times moved by {shift})"))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("files", nargs="+", type=Path, help="dt-edge readings.csv file(s) of one run")
    ap.add_argument("--publish", action="store_true", help="send to the dev broker instead of the offline summary")
    ap.add_argument("--keep-times", action="store_true", help="with --publish: send the recorded times unchanged")
    ap.add_argument("--speed", type=float, default=0, help="with --publish: N times real time (0 = as fast as possible)")
    args = ap.parse_args()
    moments = load(args.files)
    if not moments:
        print("no rows found")
        return 1
    return publish(moments, args.keep_times, args.speed) if args.publish else offline(moments)


if __name__ == "__main__":
    sys.exit(main())
