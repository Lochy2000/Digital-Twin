"""
Health: is a service WORKING, not just running? (v0.2 step D2)

`dt/v1/status/{name}` only says online/offline, and stays "online" while a service is stuck
or its machine is asleep. Each service now also sends a heartbeat every 30 s:

    dt/v1/health/{name}   (QoS 1, retained: a new subscriber sees the last one and its time)
    {"v": 1, "client": "ingestion_gateway", "time": "2026-11-20T15:40:00.000Z",
     "ok": false, "problems": ["not connected to the broker"], "uptime_s": 125, ...counters}

Reading it: "ok" false = the service knows something is wrong (problems says what). A "time"
much older than 30 s = the service, its machine or the network has stopped, so it can't say.

The same message goes to a file (default /tmp/health.json), which Docker's HEALTHCHECK reads:

    python -m dtteo_common.health /tmp/health.json 90     exit 0 = healthy, 1 = not

Healthy = the file is less than 90 s old AND says ok. No web server or extra port needed,
and the check fails both when the service reports a problem and when it stops reporting.

Pattern: heartbeat + health endpoint ("Health Endpoint Monitoring", Azure Architecture Center:
https://learn.microsoft.com/en-us/azure/architecture/patterns/health-endpoint-monitoring),
with the file standing in for the endpoint. Docker HEALTHCHECK:
https://docs.docker.com/reference/dockerfile/#healthcheck
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

INTERVAL = 30                       # seconds between heartbeats
MAX_AGE = 90                        # a heartbeat older than this means the service stopped reporting
DEFAULT_FILE = "/tmp/health.json"

log = logging.getLogger("health")

# status() returns (problems, counters): an empty problem list means healthy.
StatusFn = Callable[[], "tuple[list[str], dict]"]


def health_topic(name: str) -> str:
    return f"dt/v1/health/{name}"


def _utc_text(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class BrokerLink:
    """Is the broker connection really working? Connected, and the broker has confirmed
    something recently. A healthy service gets a confirmation at least every heartbeat (the
    heartbeat itself is QoS 1), so silence means the connection or our network thread is stuck."""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self.clock = clock
        self.is_connected = False
        self.last_confirmed = clock()

    def connected(self) -> None:
        self.is_connected = True
        self.last_confirmed = self.clock()

    def disconnected(self) -> None:
        self.is_connected = False

    def confirmed(self) -> None:                       # call from on_publish
        self.last_confirmed = self.clock()

    def problems(self, max_silence: float = 2.5 * INTERVAL) -> list[str]:
        if not self.is_connected:
            return ["not connected to the broker"]
        silent = self.clock() - self.last_confirmed
        if silent > max_silence:
            return [f"broker has confirmed nothing for {silent:.0f}s"]
        return []


class Heartbeat:
    """Every INTERVAL seconds: ask the service how it is, publish that, and write it to a file.
    Runs in its own thread, so it keeps reporting while the service's main loop is busy or
    waiting (e.g. retrying a database that is down)."""

    def __init__(self, name: str, status: StatusFn, publish: Callable[[str, str], object],
                 path: str | None = DEFAULT_FILE, interval: float = INTERVAL,
                 clock: Callable[[], float] = time.time):
        self.name, self.status, self.publish = name, status, publish
        self.path = Path(path) if path else None
        self.interval, self.clock = interval, clock
        self.started = clock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="heartbeat", daemon=True)
        self._last_ok: bool | None = None

    def beat(self) -> dict:
        try:
            problems, counters = self.status()
        except Exception as e:                         # a bug in status() is itself a problem
            problems, counters = [f"health check failed: {e!r}"], {}
        now = self.clock()
        msg = {"v": 1, "client": self.name, "time": _utc_text(now), "ok": not problems,
               "problems": problems, "uptime_s": int(now - self.started), **counters}
        text = json.dumps(msg)
        try:
            self.publish(health_topic(self.name), text)
        except Exception as e:                         # not connected etc.: the file still gets written
            log.debug("heartbeat publish failed: %r", e)
        if self.path:
            try:
                tmp = self.path.with_suffix(".tmp")
                tmp.write_text(text)
                os.replace(tmp, self.path)             # atomic: the checker never reads half a file
            except OSError as e:                       # e.g. no /tmp when run outside Docker on Windows
                log.warning("can't write heartbeat file %s (%s); set HEALTH_FILE=off to skip it", self.path, e)
                self.path = None
        if msg["ok"] != self._last_ok:                 # log changes only, not every beat
            (log.info if msg["ok"] else log.warning)(
                "health ok" if msg["ok"] else "health problem: " + "; ".join(problems))
            self._last_ok = msg["ok"]
        return msg

    def _run(self) -> None:
        while True:
            self.beat()
            if self._stop.wait(self.interval):
                return

    def start(self) -> "Heartbeat":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()


def check(path: str | Path, max_age: float = MAX_AGE, now: float | None = None) -> tuple[bool, str]:
    """(healthy, reason) from a heartbeat file."""
    path = Path(path)
    try:
        age = (time.time() if now is None else now) - path.stat().st_mtime
        msg = json.loads(path.read_text())
    except (OSError, ValueError) as e:
        return False, f"no readable heartbeat file: {e}"
    if age > max_age:
        return False, f"last heartbeat {age:.0f}s ago (limit {max_age:.0f}s)"
    if not msg.get("ok"):
        return False, "; ".join(msg.get("problems") or ["not ok"])
    return True, "ok"


def main(argv: list[str] | None = None) -> int:
    """python -m dtteo_common.health [file] [max_age_seconds]"""
    args = sys.argv[1:] if argv is None else argv
    path = args[0] if args else DEFAULT_FILE
    max_age = float(args[1]) if len(args) > 1 else MAX_AGE
    healthy, reason = check(path, max_age)
    print(reason)
    return 0 if healthy else 1


if __name__ == "__main__":
    raise SystemExit(main())
