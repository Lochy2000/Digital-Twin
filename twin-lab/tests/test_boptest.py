"""Checks the BOPTEST plant code without the internet, using a fake server.

The fake answers like BOPTEST does (status/message/payload), so these tests
check our side: unwrapping replies, unit conversion and the canonical rows.
They can't check that the real BOPTEST point names are right; that's what
`python run_boptest.py --list` is for.
"""

from datetime import datetime, timezone

import pytest

from twinlab.boptest import POINTS, BoptestClient, BoptestError, check_points, to_rows

FAKE_POINT_LIST = {
    "zon_reaTRooAir_y": {"Unit": "K", "Description": "Zone air temperature"},
    "zon_weaSta_reaWeaTDryBul_y": {"Unit": "K", "Description": "Outside dry bulb temperature"},
    "fcu_reaPHea_y": {"Unit": "W", "Description": "Heating power"},
    "fcu_reaPCoo_y": {"Unit": "W", "Description": "Cooling power"},
    "fcu_reaPFan_y": {"Unit": "W", "Description": "Fan power"},
}


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self.body


class FakeSession:
    """Remembers each request and answers like the BOPTEST web service."""

    def __init__(self):
        self.calls = []
        self.time = 0.0

    def request(self, method, url, json=None, timeout=None):
        self.calls.append((method, url, json))
        if url.endswith("/select"):
            return FakeResponse({"testid": "abc123"})
        if "/measurements/" in url:
            return FakeResponse({"status": 200, "message": "", "payload": FAKE_POINT_LIST})
        if "/advance/" in url:
            self.time += 900
            return FakeResponse({"status": 200, "message": "", "payload": {
                "time": self.time, "zon_reaTRooAir_y": 294.15, "zon_weaSta_reaWeaTDryBul_y": 278.15,
                "fcu_reaPHea_y": 1500.0, "fcu_reaPCoo_y": 0.0, "fcu_reaPFan_y": 40.0}})
        if "/initialize/" in url and json["start_time"] < 0:
            return FakeResponse({"status": 400, "message": "bad start time", "payload": None})
        return FakeResponse({"status": 200, "message": "", "payload": {}})


def test_select_keeps_the_testid_and_later_calls_use_it():
    s = FakeSession()
    c = BoptestClient("https://example.test", session=s)
    assert c.select("bestest_air") == "abc123"
    c.set_step(900)
    assert s.calls[-1] == ("PUT", "https://example.test/step/abc123", {"step": 900})


def test_replies_are_unwrapped_and_errors_raised():
    c = BoptestClient("https://example.test", session=FakeSession())
    c.select("bestest_air")
    assert c.measurements() == FAKE_POINT_LIST
    with pytest.raises(BoptestError, match="bad start time"):
        c.initialize(start_time=-1, warmup_period=0)


def test_missing_point_names_are_explained():
    with pytest.raises(BoptestError, match="--list"):
        check_points({"zon_reaTRooAir_y": {"Unit": "K"}})


def test_readings_become_canonical_rows_in_our_units():
    c = BoptestClient("https://example.test", session=FakeSession())
    c.select("bestest_air")
    plan = check_points(c.measurements())
    now = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
    rows = to_rows(c.advance(), plan, now=now)

    assert len(rows) == len(POINTS)
    by_point = {r["point"]: r for r in rows}
    assert by_point["unit1.zone_air_temp"]["value"] == pytest.approx(21.0)   # 294.15 K
    assert by_point["unit1.zone_air_temp"]["unit"] == "DEG_C"
    assert by_point["unit1.heat_output"]["value"] == pytest.approx(1.5)      # 1500 W
    assert by_point["unit1.heat_output"]["unit"] == "KiloW"
    first = rows[0]
    assert first["sensor_time"] == "2026-01-01T00:15:00.000Z"               # 900 s after 1 Jan
    assert first["ingest_time"] == "2026-11-02T12:00:00.000Z"
    assert set(first) == {"v", "site", "point", "value", "unit", "sensor_time",
                          "ingest_time", "time_source", "source", "quality"}


def test_stop_frees_the_run():
    s = FakeSession()
    c = BoptestClient("https://example.test", session=s)
    c.select("bestest_air")
    c.stop()
    assert s.calls[-1][:2] == ("PUT", "https://example.test/stop/abc123")
    assert c.testid is None
