"""
The running historian: broker in, database out (ADR-002 section 7).

    python -m historian.service          (settings from environment variables, below)

    dt/v1/telemetry/#  ─┐                              ┌─ readings
    dt/v1/quarantine/# ─┴─► buffer ─► every 1 s or 500 ─► one transaction ─┴─ quarantine
                                                       └─ then acknowledge those messages

How nothing is lost (or stored twice):
  1. Acknowledge only AFTER the database has committed. paho normally acknowledges as soon as
     on_message returns; with manual_ack_set(True) "the caller MUST manually acknowledge every
     message once application processing is complete using ack()" (paho-mqtt 2.1.0 source).
     A crash before the commit means the broker re-sends; the unique key skips copies.
  2. Database down: keep the batch, don't acknowledge, retry with a growing wait (1 s ... 30 s).
     The broker stops sending once RECEIVE_MAX messages are unacknowledged (MQTT 5 Receive
     Maximum) and holds the rest for our session, saved to disk (broker/mosquitto.conf).
  3. Acks are only valid on the connection the message arrived on. After a reconnect the
     broker re-sends anything unacknowledged, so older messages are written but not acked.
  4. Acks go out in the order messages arrived, as MQTT requires ("It MUST send PUBACK packets
     in the order in which the corresponding PUBLISH packets were received", quoted in
     https://www.hivemq.com/blog/understanding-mqtt-message-ordering/).

Settings (environment variables):
    BROKER_HOST / BROKER_PORT   default localhost / 1883
    DATABASE_URL                e.g. postgresql://historian:pw@timescaledb:5432/dtteo
    HISTORIAN_SITE              default site1: the site the asset model describes
    MODEL_DIR                   folder with dtteo_asset_model.ttl and mappings/ (default: v0.1)
    CONTRACTS_DIR               folder with the *.schema.json contracts (default: v0.1/contracts)
    BATCH_SIZE / BATCH_SECONDS  default 500 / 1.0
    LOG_LEVEL                   default INFO (DEBUG logs every batch)

Sources:
  - MQTT 5 session (clean start + expiry), as the gateway: https://www.hivemq.com/blog/mqtt5-session-message-expiry/
  - Design: decisions/ADR-002-database-layout.md
"""
from __future__ import annotations

import json
import logging
import os
import queue
import signal
import time
from dataclasses import dataclass
from pathlib import Path

import paho.mqtt.client as mqtt
from jsonschema import Draft202012Validator, FormatChecker
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties

from gateway.mapper import Mapper          # same asset-model reader as the gateway (one source of truth)
from gateway.pipeline import kv            # same logfmt log lines as the gateway

from .store import Message, PostgresHistorian, StoreUnavailable

CLIENT_ID = "historian"
STATUS_TOPIC = f"dt/v1/status/{CLIENT_ID}"
SUBSCRIPTIONS = [("dt/v1/telemetry/#", 1), ("dt/v1/quarantine/#", 1)]
SESSION_EXPIRY = 7 * 24 * 3600     # seconds the broker keeps our session while we're away
RECEIVE_MAX = 1000                 # most unacknowledged messages the broker may send us at once
MAX_WAIT = 30                      # longest wait between database retries, seconds

log = logging.getLogger("historian")
V01 = Path(__file__).resolve().parents[3] if len(Path(__file__).resolve().parents) > 3 else Path("/")


@dataclass(frozen=True)
class Received:
    message: Message
    mid: int
    qos: int
    connection: int      # which broker connection it arrived on (acks are only valid there)


def contract_validator(contracts_dir: Path):
    """function(message, kind) -> list of errors, using the JSON Schema contracts."""
    schemas = {kind: Draft202012Validator(json.loads((contracts_dir / f"{kind}_message.schema.json").read_text()),
                                          format_checker=FormatChecker())
               for kind in ("canonical", "quarantine")}
    def validate(msg: dict, kind: str) -> list[str]:
        return [f"{'/'.join(map(str, e.path)) or '(message)'}: {e.message}" for e in schemas[kind].iter_errors(msg)]
    return validate


class Batcher:
    """Collects messages, writes them, then acknowledges them. Runs in the main thread."""

    def __init__(self, store, ack, current_connection, size: int, seconds: float):
        self.store, self.ack, self.current_connection = store, ack, current_connection
        self.size, self.seconds = size, seconds
        self.inbox: queue.Queue[Received] = queue.Queue()
        self.totals = {"readings": 0, "duplicates": 0, "quarantined": 0}

    def collect(self, stop) -> list[Received]:
        """Wait for the first message, then gather more until the batch is full or time is up."""
        batch, deadline = [], None
        while not stop() and len(batch) < self.size:
            timeout = 0.5 if deadline is None else max(0.0, deadline - time.monotonic())
            try:
                batch.append(self.inbox.get(timeout=timeout))
                deadline = deadline or time.monotonic() + self.seconds
            except queue.Empty:
                if batch:
                    break
        return batch

    def flush(self, batch: list[Received], stop) -> bool:
        """Write, retrying while the database is down; then ack. False if stopped first."""
        wait = 1
        while True:
            try:
                result = self.store.write([r.message for r in batch])
                break
            except StoreUnavailable as e:
                log.warning(kv("database_unavailable", held=len(batch), waiting=self.inbox.qsize(),
                               retry_in=f"{wait}s", error=e))
                for _ in range(wait * 10):
                    if stop():
                        return False
                    time.sleep(0.1)
                wait = min(wait * 2, MAX_WAIT)
        current = self.current_connection()
        stale = 0
        for r in batch:                                   # in arrival order
            if r.connection == current:
                self.ack(r.mid, r.qos)
            else:
                stale += 1                                # broker will re-send; copies are skipped
        for k in self.totals:
            self.totals[k] += getattr(result, k)
        level = logging.INFO if (result.problems or result.duplicates or stale) else logging.DEBUG
        log.log(level, kv("batch_stored", messages=len(batch), readings=result.readings,
                          duplicates=result.duplicates, quarantined=result.quarantined,
                          not_acked_after_reconnect=stale or None))
        for reason in result.problems:
            log.warning(kv("store_quarantine", reason=reason))
        return True


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
    site = os.getenv("HISTORIAN_SITE", "site1")
    model_dir = Path(os.getenv("MODEL_DIR") or V01)
    contracts_dir = Path(os.getenv("CONTRACTS_DIR") or model_dir / "contracts")
    store = PostgresHistorian(os.environ["DATABASE_URL"], site, validate=contract_validator(contracts_dir))

    # 1. Copy the asset model's points into the series table (waits for the database).
    points = Mapper.from_folder(model_dir).points()
    wait = 1
    while True:
        try:
            n = store.sync_series(site, points)
            log.info(kv("series_synced", site=site, points=n))
            break
        except StoreUnavailable as e:
            log.warning(kv("database_unavailable", retry_in=f"{wait}s", error=e))
            time.sleep(wait)
            wait = min(wait * 2, MAX_WAIT)

    # 2. Broker: MQTT 5, persistent session, manual acknowledgements.
    connection = {"n": 0}
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=CLIENT_ID, protocol=mqtt.MQTTv5)
    client.manual_ack_set(True)
    client.will_set(STATUS_TOPIC, "offline", qos=1, retain=True)
    batcher = Batcher(store, client.ack, lambda: connection["n"],
                      int(os.getenv("BATCH_SIZE", "500")), float(os.getenv("BATCH_SECONDS", "1.0")))

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            log.error(kv("connect_failed", reason=str(reason_code)))
            return
        connection["n"] += 1
        client.subscribe(SUBSCRIPTIONS)
        client.publish(STATUS_TOPIC, "online", qos=1, retain=True)
        log.info(kv("connected", session_present=flags.session_present, connection=connection["n"]))

    def on_disconnect(client, userdata, flags, reason_code, properties):
        log.warning(kv("disconnected", reason=str(reason_code)))

    def on_message(client, userdata, msg):
        # Network thread: just hand over. Writing happens in the main thread.
        batcher.inbox.put(Received(Message(msg.topic, msg.payload), msg.mid, msg.qos, connection["n"]))

    client.on_connect, client.on_disconnect, client.on_message = on_connect, on_disconnect, on_message
    props = Properties(PacketTypes.CONNECT)
    props.SessionExpiryInterval = SESSION_EXPIRY
    props.ReceiveMaximum = RECEIVE_MAX
    client.connect_async(os.getenv("BROKER_HOST", "localhost"), int(os.getenv("BROKER_PORT", "1883")),
                         clean_start=False, properties=props)
    client.loop_start()

    stopping = {"now": False}
    signal.signal(signal.SIGTERM, lambda *_: stopping.update(now=True))      # docker compose stop
    stop = lambda: stopping["now"]
    last_report = time.monotonic()
    try:
        while not stop():
            batch = batcher.collect(stop)
            if batch and not batcher.flush(batch, stop):
                break
            if time.monotonic() - last_report >= 60:                        # one summary a minute
                log.info(kv("stored_last_minute", **batcher.totals))
                batcher.totals = dict.fromkeys(batcher.totals, 0)
                last_report = time.monotonic()
    except KeyboardInterrupt:
        pass
    # Unacknowledged messages stay with the broker and come back next time.
    client.publish(STATUS_TOPIC, "offline", qos=1, retain=True).wait_for_publish(timeout=2)
    client.disconnect()
    client.loop_stop()
    store.close()


if __name__ == "__main__":
    main()
