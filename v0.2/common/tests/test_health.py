"""v0.2 step D2: heartbeat message, heartbeat file and the Docker health check."""
import json
import os

from dtteo_common import health
from dtteo_common.health import BrokerLink, Heartbeat, check


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


def test_broker_link():
    clock = Clock()
    link = BrokerLink(clock)
    assert link.problems() == ["not connected to the broker"]
    link.connected()
    assert link.problems() == []
    clock.t += 80                                      # no confirmation for 80 s
    assert link.problems()[0].startswith("broker has confirmed nothing")
    link.confirmed()
    assert link.problems() == []
    link.disconnected()
    assert link.problems() == ["not connected to the broker"]


def test_heartbeat_publishes_and_writes_the_same_message(tmp_path):
    sent = []
    hb = Heartbeat("historian", lambda: ([], {"stored": 5}), lambda t, p: sent.append((t, p)),
                   path=tmp_path / "health.json", clock=Clock(1_700_000_000.0))
    msg = hb.beat()
    assert sent[0][0] == "dt/v1/health/historian"
    assert json.loads(sent[0][1]) == msg == json.loads((tmp_path / "health.json").read_text())
    assert msg["ok"] is True and msg["stored"] == 5 and msg["time"].endswith("Z")


def test_a_broken_status_or_publish_still_writes_an_unhealthy_file(tmp_path):
    def boom():
        raise RuntimeError("bug")

    def no_broker(topic, text):
        raise OSError("not connected")

    hb = Heartbeat("x", boom, no_broker, path=tmp_path / "h.json")
    assert hb.beat()["ok"] is False
    assert check(tmp_path / "h.json")[0] is False


def test_check(tmp_path):
    f = tmp_path / "h.json"
    healthy, reason = check(f)
    assert not healthy and "no readable heartbeat" in reason
    f.write_text(json.dumps({"ok": True}))
    assert check(f) == (True, "ok")
    assert check(f, now=os.path.getmtime(f) + 91)[1].startswith("last heartbeat")     # stopped reporting
    f.write_text(json.dumps({"ok": False, "problems": ["database unavailable for 40s"]}))
    assert check(f) == (False, "database unavailable for 40s")


def test_main_exit_codes(tmp_path, capsys):
    f = tmp_path / "h.json"
    f.write_text(json.dumps({"ok": True}))
    assert health.main([str(f)]) == 0
    assert health.main([str(tmp_path / "missing.json")]) == 1
