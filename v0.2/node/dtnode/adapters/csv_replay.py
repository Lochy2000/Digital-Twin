"""
CSV replay: plays a recorded dt-edge run back as if the sensors were live (times = now),
at real speed or faster. Gives realistic data on a laptop, or on a node with no sensors yet.

    [[sensors]]
    id = "replay"
    type = "csv"
    poll_s = 0.5
    files = ["part1.csv", "part2.csv", "part3.csv"]     # one run, possibly saved in parts
    speed = 1                                          # 2 = twice real speed
    loop = true                                        # start again at the end

Reads both dt-edge downloads (header decides): "All readings" (point_id column) and "Excel CSV"
(columns "Label (unit) [point_id]"). Point ids come from the file (e.g. lepton.max), so the
gateway maps them exactly as it would the real rig.
"""
from __future__ import annotations

import csv
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from dtnode.adapters.base import Adapter
from dtnode.reading import Reading

HEADER_UNITS = {"degC": "DEG_C", "%RH": "PERCENT_RH", "hPa": "HectoPA", "W": "W", "kWh": "KiloW-HR"}
WIDE_COLUMN = re.compile(r"^.*?\s*(\((?P<unit>[^()]*)\))?\s*\[(?P<point>[^\[\]]+)\]$")


def _value(point: str, text: str):
    if point.endswith(".on"):
        return text.strip() in ("1", "True", "true")       # dt-edge writes booleans as 1 / 0
    try:
        number = float(text)
    except ValueError:
        return text
    return int(number) if number.is_integer() and "." not in text else number


def _time(text: str) -> float:
    t = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return (t if t.tzinfo else t.replace(tzinfo=timezone.utc)).timestamp()


def load_run(files: list[Path]) -> list[tuple[float, list[tuple[str, object, str | None]]]]:
    """[(seconds since the run started, [(point_id, value, unit), ...]), ...], oldest first."""
    moments: dict[float, list] = {}
    for f in files:
        with open(f, newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            header = reader.fieldnames or []
            if "point_id" in header:
                for row in reader:
                    if row["value"] != "":
                        moments.setdefault(_time(row["time"]), []).append(
                            (row["point_id"], _value(row["point_id"], row["value"]), row.get("unit") or None))
                continue
            columns = {c: WIDE_COLUMN.match(c) for c in header if c not in ("time", "t_s")}
            if "time" not in header or not all(columns.values()):
                raise ValueError(f"{f}: not a dt-edge CSV")
            for row in reader:
                t = _time(row["time"])
                for col, m in columns.items():
                    text = (row.get(col) or "").strip()
                    if text:
                        unit = (m["unit"] or "").strip()
                        moments.setdefault(t, []).append((m["point"], _value(m["point"], text), HEADER_UNITS.get(unit, unit or None)))
    if not moments:
        raise ValueError("no readings in " + ", ".join(map(str, files)))
    first = min(moments)
    return [(t - first, moments[t]) for t in sorted(moments)]


class CsvReplayAdapter(Adapter):
    def connect(self) -> None:
        files = [Path(f).expanduser() for f in self.cfg.get("files", [])]
        if not files:
            raise ValueError(f"csv sensor {self.id!r}: no files")
        self.run = load_run(files)
        self.speed = float(self.cfg.get("speed", 1))
        self.loop = bool(self.cfg.get("loop", True))
        self._restart()

    def _restart(self) -> None:
        self.started, self.next = time.monotonic(), 0

    def read(self) -> list[Reading]:
        if self.next >= len(self.run):
            if not self.loop:
                return []
            self._restart()
        elapsed, now, out = (time.monotonic() - self.started) * self.speed, self.now(), []
        while self.next < len(self.run) and self.run[self.next][0] <= elapsed:
            out += [Reading(p, v, u, now) for p, v, u in self.run[self.next][1]]
            self.next += 1
        return out

    @property
    def source(self) -> str:
        return f"csv:{self.id}"
