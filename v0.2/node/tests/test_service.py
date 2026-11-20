"""The sender's rules, with a fake MQTT client (no broker needed)."""
import json
import threading
import time

from dtnode.config import load
from dtnode.outbox import Outbox
from dtnode.service import MAX_IN_FLIGHT, Sender, SensorThread


class FakeInfo:
    def __init__(self, mid, rc=0):
        self.mid, self.rc = mid, rc


class FakeClient:
    def __init__(self):
        self.sent, self.mid = [], 0

    def publish(self, topic, payload, qos):
        self.mid += 1
        self.sent.append((self.mid, topic, payload))
        return FakeInfo(self.mid)


def test_nothing_is_sent_while_disconnected(tmp_path):
    box = Outbox(tmp_path / "o.db"); box.put("t", b"x")
    s = Sender(FakeClient(), box)
    assert s.send_some() == 0 and box.count() == 1


def test_a_message_leaves_the_outbox_only_when_the_broker_confirms_it(tmp_path):
    box, client = Outbox(tmp_path / "o.db"), FakeClient()
    box.put("t", b"x")
    s = Sender(client, box); s.on_connect()
    assert s.send_some() == 1 and box.count() == 1          # sent, not yet confirmed
    s.on_published(client.sent[0][0])
    assert box.count() == 0


def test_unconfirmed_messages_are_sent_again_after_a_reconnect(tmp_path):
    box, client = Outbox(tmp_path / "o.db"), FakeClient()
    box.put("t", b"x")
    s = Sender(client, box); s.on_connect(); s.send_some()
    s.on_disconnect(); s.on_connect()                        # link dropped before the confirmation
    assert s.send_some() == 1 and len(client.sent) == 2


def test_no_more_than_the_in_flight_limit_at_once(tmp_path):
    box, client = Outbox(tmp_path / "o.db"), FakeClient()
    for i in range(MAX_IN_FLIGHT + 5):
        box.put("t", str(i).encode())
    s = Sender(client, box); s.on_connect()
    assert s.send_some() == MAX_IN_FLIGHT and s.send_some() == 0


def test_sensor_polls_land_in_the_outbox_as_dtedge_messages(tmp_path):
    (tmp_path / "node.toml").write_text('''
name = "test_node"
[outbox]
path = "unused.db"
[[sensors]]
id = "tc08"
type = "simulated"
poll_s = 0.05
unit = "DEG_C"
[sensors.metrics]
ch1 = { start = 30, end = 5, tau_s = 600 }
ch2 = { start = 28 }
''')
    node, box, stop = load(tmp_path / "node.toml", env={}), Outbox(tmp_path / "o.db"), threading.Event()
    t = SensorThread(node.sensors[0], node, box, stop); t.start()
    time.sleep(0.3); stop.set(); t.join(2)
    rows = box.oldest(100)
    assert len(rows) >= 3 and all(topic == "raw/dtedge/test_node/telemetry" for _, topic, _ in rows)
    msg = json.loads(rows[0][2])
    assert [m["point_id"] for m in msg] == ["tc08.ch1", "tc08.ch2"]
    assert msg[0]["v"] == 2 and msg[0]["unit"] == "DEG_C" and msg[0]["source"] == "simulated:tc08"
    assert msg[0]["sensor_time"].endswith("+00:00")


def test_a_failing_sensor_is_retried_without_stopping(tmp_path):
    (tmp_path / "node.toml").write_text('name = "n"\n[[sensors]]\nid = "bad"\ntype = "csv"\nfiles = ["/nowhere.csv"]\n')
    node, box, stop = load(tmp_path / "node.toml", env={}), Outbox(tmp_path / "o.db"), threading.Event()
    t = SensorThread(node.sensors[0], node, box, stop); t.start()
    time.sleep(0.2); stop.set(); t.join(3)
    assert not t.is_alive() and box.count() == 0
