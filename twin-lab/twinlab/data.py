"""Reading plant recordings (canonical CSV) into a shape the twin can step through.

The CSV is "long": one row per reading, so one moment in time is spread over
several rows (zone temp, outside temp, heating ... each on its own row).

    sensor_time            point                      value
    2026-01-15T00:15Z      unit1.zone_air_temp        15.0
    2026-01-15T00:15Z      weather1.outside_air_temp  -6.1
    2026-01-15T00:15Z      unit1.heat_output          0.02

The twin works one moment at a time, so we turn it "wide": one dict per moment,
holding every reading taken at that time.

    {"time": 2026-01-15 00:15, "unit1.zone_air_temp": 15.0,
     "weather1.outside_air_temp": -6.1, "unit1.heat_output": 0.02, ...}
"""

import csv
from datetime import datetime


def load_timesteps(path) -> list[dict]:
    """Read a canonical CSV into a list of moments, oldest first."""
    moments = {}  # time -> {"time": time, point: value, ...}
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            # "2026-01-15T00:15:00.000Z" -> a Python datetime ("Z" means UTC)
            t = datetime.fromisoformat(row["sensor_time"].replace("Z", "+00:00"))
            moment = moments.setdefault(t, {"time": t})  # make it the first time we see t
            moment[row["point"]] = float(row["value"])   # all BOPTEST values are numbers
    return [moments[t] for t in sorted(moments)]


def split_days(moments: list[dict]) -> list[list[dict]]:
    """Group moments by calendar day (UTC). Each day becomes one segment."""
    days = {}
    for m in moments:
        days.setdefault(m["time"].date(), []).append(m)
    return [days[d] for d in sorted(days)]


def find_cooldowns(moments: list[dict], min_moments: int = 8) -> list[list[dict]]:
    """Find stretches where the room cools on its own: unit off and no sun.

    These are RR 1 §7's "free step-response experiments": with no heat from
    the unit or the sun, how fast the room cools shows R and C directly.
    `min_moments` = 8 means at least 2 hours at 15-minute steps.
    """
    def free(m):
        return (m["unit1.heat_output"] < 0.005        # heating off (under 5 W)
                and m["unit1.cool_power"] < 0.005     # cooling off
                and m["weather1.solar_global"] < 1)   # dark

    runs, current = [], []
    for m in moments:
        if free(m):
            current.append(m)
        else:
            if len(current) >= min_moments:
                runs.append(current)
            current = []
    if len(current) >= min_moments:
        runs.append(current)
    return runs
