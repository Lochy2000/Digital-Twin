"""
The node's heartbeat (v0.2 step D3): every 30 s, on dt/v1/health/{name} (QoS 1, retained).

Same message shape as the gateway's and historian's (common/contracts/topics.md, "Health
heartbeat"), built here in a few lines so the node needs nothing but paho (no dtteo_common):

    {"v": 1, "client": "digitwin_pi", "time": "...Z", "ok": false,
     "problems": ["sensor lepton: no reading for 45s (OSError('camera not found'))"],
     "uptime_s": 3600, "waiting": 0, "dropped": 0, "sensors": {"tc08": "ok", "lepton": "failing"}}

Problems:
  - a sensor hasn't read successfully for more than 3 polls (plus a few seconds' grace);
  - the outbox dropped readings since the last heartbeat (it was full).
Only sent while connected. No heartbeat for over 90 s = the node, its power or its network is
down: on a Pi Zero there's no Docker to say so, so whoever reads the heartbeats decides.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

INTERVAL = 30                     # seconds between heartbeats
GRACE_S = 5                       # on top of 3 polls before a sensor counts as failing


def is_failing(poll_s: float, last_ok: float, now: float) -> bool:
    return now - last_ok > 3 * poll_s + GRACE_S


def message(name: str, sensors: list, waiting: int, dropped: int, dropped_before: int,
            started: float, now: float | None = None, wall: float | None = None) -> dict:
    """sensors: objects with .sensor_id, .poll_s, .last_ok (monotonic) and .last_error."""
    now = time.monotonic() if now is None else now
    wall = time.time() if wall is None else wall
    problems, states = [], {}
    for s in sensors:
        if is_failing(s.poll_s, s.last_ok, now):
            states[s.sensor_id] = "failing"
            why = f" ({s.last_error})" if s.last_error else ""
            problems.append(f"sensor {s.sensor_id}: no reading for {now - s.last_ok:.0f}s{why}")
        else:
            states[s.sensor_id] = "ok"
    if dropped > dropped_before:
        problems.append(f"outbox full: {dropped - dropped_before} readings dropped since the last heartbeat")
    when = datetime.fromtimestamp(wall, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return {"v": 1, "client": name, "time": when, "ok": not problems, "problems": problems,
            "uptime_s": int(now - started), "waiting": waiting, "dropped": dropped, "sensors": states}
