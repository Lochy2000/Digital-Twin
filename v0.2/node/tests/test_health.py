"""v0.2 step D3: the node's heartbeat says which sensors are reading and whether the outbox overflowed."""
from types import SimpleNamespace

from dtnode import health


def sensor(sensor_id, poll_s, last_ok, last_error=None):
    return SimpleNamespace(sensor_id=sensor_id, poll_s=poll_s, last_ok=last_ok, last_error=last_error)


def test_all_reading_is_healthy():
    msg = health.message("digitwin_pi", [sensor("tc08", 1, 99.5)], waiting=0, dropped=0, dropped_before=0,
                         started=0, now=100, wall=1_795_190_000)
    assert msg["ok"] and msg["problems"] == [] and msg["sensors"] == {"tc08": "ok"}
    assert msg["client"] == "digitwin_pi" and msg["time"].endswith("Z") and msg["uptime_s"] == 100


def test_a_sensor_silent_for_more_than_three_polls_is_a_problem():
    slow_ok = sensor("ambient", 10, 100 - 30)                  # 3 polls = 30 s, plus grace: still ok
    failing = sensor("lepton", 1, 100 - 45, "OSError('camera not found')")
    msg = health.message("n", [slow_ok, failing], 0, 0, 0, started=0, now=100)
    assert msg["sensors"] == {"ambient": "ok", "lepton": "failing"}
    assert msg["problems"] == ["sensor lepton: no reading for 45s (OSError('camera not found'))"]


def test_outbox_drops_since_the_last_heartbeat_are_a_problem():
    msg = health.message("n", [], waiting=10_000, dropped=7, dropped_before=2, started=0, now=1)
    assert msg["problems"] == ["outbox full: 5 readings dropped since the last heartbeat"]
    assert health.message("n", [], 10_000, 7, 7, 0, now=1)["ok"]       # old drops already reported
