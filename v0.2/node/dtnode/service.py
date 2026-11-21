"""
The running node: sensors -> outbox -> broker.

    python -m dtnode.service node.toml        (password: env MQTT_PASSWORD)

  - One thread per sensor reads on its own timer (poll_s) and puts each poll, as ONE message
    (a list of readings), into the outbox. A sensor that errors is closed and reconnected with
    a growing wait (1 s ... 60 s); the other sensors carry on.
  - The sender takes the oldest messages from the outbox, publishes them (QoS 1), and removes
    each only when the broker confirms it (on_publish). Up to MAX_IN_FLIGHT at a time.
    Disconnected: nothing is sent, the outbox fills, and is emptied oldest-first on reconnect.
  - Broker gone: paho reconnects by itself; RECONNECT_MAX_S keeps the retries frequent.
  - Online/offline: "online" (retained) on dt/v1/status/{name}; the broker publishes "offline"
    for us if we vanish (Last Will), the same as every other client (contracts/topics.md).
  - Health: every 30 s, while connected, a heartbeat on dt/v1/health/{name}: which sensors are
    reading, outbox size and drops (dtnode/health.py). Sent directly, not through the outbox:
    it's current state, so an old one arriving late would mislead.

What it does NOT do: check, convert or interpret readings. That is the gateway's job.

Sources: paho-mqtt 2.x callbacks https://eclipse.dev/paho/files/paho.mqtt.python/html/migrations.html
"""
from __future__ import annotations

import json
import logging
import signal
import sys
import threading
import time

from dtnode import adapters, health
from dtnode.config import ConfigError, NodeConfig, load
from dtnode.outbox import Outbox

MAX_IN_FLIGHT = 20               # messages sent but not yet confirmed by the broker
RECONNECT_MAX_S = 5              # retry the broker at least this often (paho's default grows to 120 s)
BATCH = 50                       # how many the sender takes from the outbox at a time
log = logging.getLogger("dtnode")


class SensorThread(threading.Thread):
    """Reads one sensor on its timer and puts each poll into the outbox."""

    def __init__(self, cfg: dict, node: NodeConfig, outbox: Outbox, stop: threading.Event):
        super().__init__(name=f"sensor-{cfg['id']}", daemon=True)
        self.cfg, self.node, self.outbox, self.stop = cfg, node, outbox, stop
        self.sensor_id = cfg["id"]
        self.poll_s = float(cfg.get("poll_s", 1))
        self.last_ok = time.monotonic()                 # last successful read (start = grace period)
        self.last_error: str | None = None              # for the heartbeat

    def run(self) -> None:
        wait = 1.0
        while not self.stop.is_set():
            adapter = None
            try:
                adapter = adapters.make(self.cfg)
                adapter.connect()
                log.info("sensor %s connected (%s)", self.cfg["id"], self.cfg["type"])
                wait = 1.0
                next_at = time.monotonic()
                while not self.stop.is_set():
                    readings = adapter.read()
                    self.last_ok, self.last_error = time.monotonic(), None
                    if readings:
                        payload = json.dumps([r.to_message(adapter.source) for r in readings]).encode()
                        self.outbox.put(self.node.topic, payload)
                    next_at += self.poll_s
                    self.stop.wait(max(0.0, next_at - time.monotonic()))
            except Exception as e:                      # one sensor failing must not stop the others
                self.last_error = repr(e)[:200]
                log.warning("sensor %s: %r; retrying in %.0f s", self.cfg["id"], e, wait)
                self.stop.wait(wait)
                wait = min(wait * 2, 60.0)
            finally:
                if adapter is not None:
                    try:
                        adapter.close()
                    except Exception:
                        pass


class Sender:
    """Moves messages from the outbox to the broker; removes each once the broker confirms it."""

    def __init__(self, client, outbox: Outbox):
        self.client, self.outbox = client, outbox
        self.in_flight: dict[int, int] = {}             # MQTT message id -> outbox row id
        self.connected = False
        self._lock = threading.Lock()

    def on_connect(self) -> None:
        with self._lock:
            self.in_flight.clear()                      # unconfirmed sends are sent again (may arrive twice: fine)
            self.connected = True

    def on_disconnect(self) -> None:
        with self._lock:
            self.connected = False

    def on_published(self, mid: int) -> None:
        with self._lock:
            row = self.in_flight.pop(mid, None)
        if row is not None:
            self.outbox.remove(row)

    def send_some(self) -> int:
        """Send what fits in the in-flight window. Returns how many were sent."""
        with self._lock:
            if not self.connected:
                return 0
            room = MAX_IN_FLIGHT - len(self.in_flight)
            busy = set(self.in_flight.values())
        if room <= 0:
            return 0
        sent = 0
        for row_id, topic, payload in self.outbox.oldest(min(room, BATCH), skip=busy):
            info = self.client.publish(topic, payload, qos=1)
            if info.rc != 0:                            # not connected after all: try again later
                break
            with self._lock:
                self.in_flight[info.mid] = row_id
            sent += 1
        return sent


def run(node: NodeConfig) -> None:
    import paho.mqtt.client as mqtt                     # imported here so tests can run without it

    outbox = Outbox(node.outbox_path, node.outbox_max)
    stop = threading.Event()
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=node.name, protocol=mqtt.MQTTv5)
    if node.password:
        client.username_pw_set(node.name, node.password)
    client.will_set(node.status_topic, "offline", qos=1, retain=True)
    client.max_inflight_messages_set(MAX_IN_FLIGHT)
    client.reconnect_delay_set(min_delay=1, max_delay=RECONNECT_MAX_S)   # back within 5 s of the broker returning
    sender = Sender(client, outbox)

    def on_connect(c, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            log.error("broker refused the connection: %s", reason_code)
            return
        c.publish(node.status_topic, "online", qos=1, retain=True)
        sender.on_connect()
        log.info("connected to %s:%s; %d message(s) waiting in the outbox", node.broker_host, node.broker_port, outbox.count())

    def on_disconnect(c, userdata, flags, reason_code, properties):
        sender.on_disconnect()
        log.warning("disconnected (%s); readings keep going into the outbox", reason_code)

    client.on_connect, client.on_disconnect = on_connect, on_disconnect
    client.on_publish = lambda c, userdata, mid, reason_code, properties: sender.on_published(mid)

    def shutdown(*_):
        stop.set()
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    sensors = [SensorThread(s, node, outbox, stop) for s in node.sensors if s.get("enabled", True)]
    for t in sensors:
        t.start()
    started, last_health, dropped_before = time.monotonic(), float("-inf"), 0
    client.connect_async(node.broker_host, node.broker_port)
    client.loop_start()
    log.info("node %s started: %d sensor(s), outbox %s", node.name, len(node.sensors), node.outbox_path)

    last_report = time.monotonic()
    while not stop.is_set():
        if sender.send_some() == 0:
            stop.wait(0.1)
        if sender.connected and time.monotonic() - last_health >= health.INTERVAL:
            msg = health.message(node.name, sensors, outbox.count(), outbox.dropped, dropped_before, started)
            client.publish(node.health_topic, json.dumps(msg), qos=1, retain=True)
            if not msg["ok"]:
                log.warning("health problem: %s", "; ".join(msg["problems"]))
            last_health, dropped_before = time.monotonic(), outbox.dropped
        if time.monotonic() - last_report >= 60:
            log.info("outbox: %d waiting, %d dropped (outbox full) so far", outbox.count(), outbox.dropped)
            last_report = time.monotonic()

    if sender.connected:                                 # if not, the broker's Last Will says "offline" for us
        try:
            client.publish(node.status_topic, "offline", qos=1, retain=True).wait_for_publish(timeout=2)
        except (RuntimeError, ValueError):
            pass
    client.disconnect()
    client.loop_stop()
    outbox.close()
    log.info("node stopped")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if len(sys.argv) != 2:
        sys.exit("usage: python -m dtnode.service node.toml")
    try:
        node = load(sys.argv[1])
    except ConfigError as e:
        sys.exit(f"config problem: {e}")
    run(node)


if __name__ == "__main__":
    main()
