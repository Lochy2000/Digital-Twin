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
