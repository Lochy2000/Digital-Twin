"""BOPTEST as the "plant": the pretend real world the twin is checked against.

What BOPTEST is
---------------
BOPTEST (IBPSA, BSD licence) runs detailed building models on a server. You
pick a test case, then repeatedly ask it to "advance" one step; each time it
moves the simulated building forward and sends back its sensor readings. Its
own built-in controller runs the heating and cooling unless we override it,
so here we just watch, like the twin would watch a real site.

API used (from the BOPTEST user guide, v0.9.0):
  POST testcases/{name}/select   -> returns a testid for our run
  GET  measurements/{testid}     -> list of sensor points, with units
  PUT  initialize/{testid}       -> start_time, warmup_period (seconds)
  PUT  step/{testid}             -> step (seconds per advance)
  POST advance/{testid}          -> readings at the end of the step
  PUT  stop/{testid}             -> end our run on the server
Replies look like {"status": 200, "message": "...", "payload": {...}}.

This file has two parts:
  1. BoptestClient: sends the requests above. The only part that talks to
     the network.
  2. to_rows(): turns one set of BOPTEST readings into canonical-message rows
     (the same shape the v0.1 gateway publishes). Pure Python, easy to test.

Swapping BOPTEST for something else later (our own simulator, the test rig)
only means producing the same rows another way.
"""

from datetime import datetime, timedelta, timezone

PUBLIC_URL = "https://api.boptest.net"

# BOPTEST time is "seconds since 1 January" of a simulated year. We label it
# 2026 so it reads as a date; it is simulated time, not a real date.
SIM_YEAR_START = datetime(2026, 1, 1, tzinfo=timezone.utc)

# Which BOPTEST readings we keep, and the point ID each becomes.
# The BOPTEST names are for the single-zone test case "bestest_air" and MUST be
# checked against `python run_boptest.py --list` before trusting them.
# heat_output / cool_output are sandbox-only points (heat delivered by the
# unit); they are not in v0.1's asset model yet.
POINTS = {
    "zon_reaTRooAir_y": "unit1.zone_air_temp",
    "zon_weaSta_reaWeaTDryBul_y": "weather1.outside_air_temp",
    "fcu_reaPHea_y": "unit1.heat_output",
    "fcu_reaPCoo_y": "unit1.cool_output",
    "fcu_reaPFan_y": "unit1.power",
}

# BOPTEST unit -> (our QUDT unit ID, conversion). Units are read from BOPTEST's
# own point list, so nothing about units is guessed here.
UNIT_CONVERSIONS = {
    "K": ("DEG_C", lambda v: v - 273.15),
    "W": ("KiloW", lambda v: v / 1000),
}


class BoptestError(RuntimeError):
    pass


class BoptestClient:
    def __init__(self, base_url: str = PUBLIC_URL, session=None, timeout: float = 120):
        if session is None:
            import requests  # only needed when really talking to BOPTEST
            session = requests.Session()
        self.base_url = base_url.rstrip("/")
        self.session = session
        self.timeout = timeout
        self.testid = None

    def _call(self, method: str, path: str, json=None):
        r = self.session.request(method, f"{self.base_url}/{path}", json=json, timeout=self.timeout)
        r.raise_for_status()
        body = r.json()
        # Most replies wrap the data in status/message/payload; unwrap it.
        if isinstance(body, dict) and "payload" in body:
            if body.get("status", 200) != 200:
                raise BoptestError(f"{path}: {body.get('message')}")
            return body["payload"]
        return body

    def select(self, testcase: str) -> str:
        reply = self._call("POST", f"testcases/{testcase}/select")
        self.testid = reply["testid"]
        return self.testid

    def measurements(self) -> dict:
        return self._call("GET", f"measurements/{self.testid}")

    def initialize(self, start_time: float, warmup_period: float) -> dict:
        return self._call("PUT", f"initialize/{self.testid}",
                          {"start_time": start_time, "warmup_period": warmup_period})

    def set_step(self, seconds: float) -> None:
        self._call("PUT", f"step/{self.testid}", {"step": seconds})

    def advance(self, inputs: dict | None = None) -> dict:
        # No inputs = let BOPTEST's own controller run the unit.
        return self._call("POST", f"advance/{self.testid}", inputs or {})

    def stop(self) -> None:
        if self.testid:
            self._call("PUT", f"stop/{self.testid}")
            self.testid = None


def check_points(point_list: dict) -> dict:
    """Return {boptest_name: (point_id, our_unit, convert)}, or explain what's missing."""
    missing = [name for name in POINTS if name not in point_list]
    if missing:
        raise BoptestError(
            f"BOPTEST has no point(s) {missing}. Run `python run_boptest.py --list` "
            f"and fix POINTS in twinlab/boptest.py.")
    plan = {}
    for name, point_id in POINTS.items():
        unit = point_list[name].get("Unit")
        if unit not in UNIT_CONVERSIONS:
            raise BoptestError(f"{name}: unit {unit!r} has no conversion in UNIT_CONVERSIONS")
        our_unit, convert = UNIT_CONVERSIONS[unit]
        plan[name] = (point_id, our_unit, convert)
    return plan


def to_rows(readings: dict, plan: dict, site: str = "site1",
            source: str = "boptest:bestest_air", now: datetime | None = None) -> list[dict]:
    """One BOPTEST reply -> one canonical-message row per kept point."""
    sensor_time = SIM_YEAR_START + timedelta(seconds=float(readings["time"]))
    ingest_time = now or datetime.now(timezone.utc)
    rows = []
    for name, (point_id, unit, convert) in plan.items():
        rows.append({
            "v": 2,
            "site": site,
            "point": point_id,
            "value": round(convert(float(readings[name])), 4),
            "unit": unit,
            "sensor_time": _iso(sensor_time),
            "ingest_time": _iso(ingest_time),
            "time_source": "device",
            "source": source,
            "quality": "GOOD",  # raw plant output; the v0.1 validator isn't run here
        })
    return rows


def _iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"
