"""
The running ingestion gateway: connects to the MQTT broker and runs the pipeline.

    python -m gateway.service          (settings from environment variables, below)

What it does:
  - subscribes to  raw/#  (QoS 1)
  - for each message, runs gateway/pipeline.py and publishes the results
  - announces itself on  dt/v1/status/ingestion_gateway  (online, with "offline" as Last Will)

Protocol: MQTT 5 (step 2j). v0.1's design leans on MQTT 5 features (shared subscriptions,
request/response), so the gateway speaks it too. In MQTT 5, "keep my session while I'm away"
is clean_start=False PLUS a Session Expiry Interval above 0; with no interval the session
ends at disconnect (HiveMQ, MQTT 5 Essentials part 4).

Not losing data when something restarts (the "small buffer" in v0.1/README.md):
  - Broker down: paho keeps QoS 1 messages it couldn't send yet and sends them after it
    reconnects (paho-mqtt 2.1.0, Client.publish). Capped by MAX_QUEUED so memory can't run away;
    if the cap is hit, paho refuses the message (MQTT_ERR_QUEUE_SIZE) and we log an ERROR.
  - Gateway down: the broker keeps raw QoS 1 messages for our session (SESSION_EXPIRY) and
    delivers them when we're back. How many it keeps is the broker's max_queued_messages, and
    whether they survive a BROKER restart is its persistence setting (broker/mosquitto.conf).

Settings (environment variables):
    BROKER_HOST       default localhost
    BROKER_PORT       default 1883
    GATEWAY_SITE      default site1   (the {site} level in canonical topics; topics.md)
    MODEL_DIR         folder holding dtteo_asset_model.ttl and mappings/  (default: v0.1)
    GATEWAY_ENABLED   optional on/off overrides for bindings, e.g.
                      "acme_hvac_0001=off,site4_hvac_01=on"  (to match the compose profile)
    LOG_LEVEL         default INFO  (DEBUG also logs every GOOD reading)

Sources:
  - paho-mqtt 2.x callbacks (on_connect(client, userdata, flags, reason_code, properties), ...):
      https://eclipse.dev/paho/files/paho.mqtt.python/html/migrations.html
  - Mosquitto max_queued_messages, persistence:  https://mosquitto.org/man/mosquitto-conf-5.html
  - MQTT 5 clean start + session expiry (replaces clean_session):
      https://www.hivemq.com/blog/mqtt5-session-message-expiry/
  - Last Will, retained status, QoS 1, persistent sessions:  MQTT spec
      https://docs.oasis-open.org/mqtt/mqtt/v5.0/os/mqtt-v5.0-os.html
  - Topics and status rules:  v0.1/contracts/topics.md
"""
from __future__ import annotations

import json
import logging
import os
import signal
import time
from datetime import datetime, timezone
from pathlib import Path

import paho.mqtt.client as mqtt
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties

from .mapper import Mapper
from .pipeline import Outgoing, Pipeline, kv

CLIENT_ID = "ingestion_gateway"                        # lowercase + "_" only (topics.md rule 2)
STATUS_TOPIC = f"dt/v1/status/{CLIENT_ID}"
SUBSCRIPTION = "raw/#"
MAX_QUEUED = 10_000                                    # outgoing messages held while the broker is away
SESSION_EXPIRY = 7 * 24 * 3600                         # seconds the broker keeps our session while we're away

log = logging.getLogger("gateway")


def parse_enabled(text: str) -> dict[str, bool]:
    """'acme_hvac_0001=off,site4_hvac_01=on' -> {'acme_hvac_0001': False, 'site4_hvac_01': True}"""
    out = {}
    for item in filter(None, (part.strip() for part in text.split(","))):
        device, _, state = item.partition("=")
        if state.strip().lower() not in ("on", "off"):
            raise ValueError(f"GATEWAY_ENABLED: expected device=on|off, got {item!r}")
        out[device.strip()] = state.strip().lower() == "on"
    return out


def send(client: mqtt.Client, o: Outgoing) -> None:
    """Publish one message and say so if it couldn't even be queued (it would be lost)."""
    info = client.publish(o.topic, json.dumps(o.payload), qos=o.qos, retain=o.retain)
    if info.rc == mqtt.MQTT_ERR_QUEUE_SIZE:
        # paho refuses new messages once MAX_QUEUED are waiting: this one is LOST.
        log.error(kv("publish_dropped", topic=o.topic, reason="outgoing queue full",
                     max_queued=MAX_QUEUED, point=o.payload.get("point")))
    elif info.rc not in (mqtt.MQTT_ERR_SUCCESS, mqtt.MQTT_ERR_NO_CONN):
        # NO_CONN is normal while reconnecting: paho keeps the message and sends it later.
        log.warning(kv("publish_problem", topic=o.topic, rc=mqtt.error_string(info.rc)))


def build_pipeline() -> Pipeline:
    # Do not calculate the source-tree fallback when MODEL_DIR is configured.
    # The container installs this module at /app/gateway/service.py, where parents[3]
    # does not exist, even though Compose correctly supplies MODEL_DIR=/model.
    configured_model_dir = os.getenv("MODEL_DIR")
    model_dir = (Path(configured_model_dir) if configured_model_dir
                 else Path(__file__).resolve().parents[3])
    mapper = Mapper.from_folder(model_dir, enabled=parse_enabled(os.getenv("GATEWAY_ENABLED", "")))
    for note in mapper.report:
        log.info(kv("mapper_note", note=note))
    log.info(kv("mapper_loaded", model_dir=str(model_dir), field_mappings=len(mapper)))
    return Pipeline(mapper, site=os.getenv("GATEWAY_SITE", "site1"))


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(message)s")
    pipeline = build_pipeline()     # a broken model or mapping stops us here, before connecting

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=CLIENT_ID, protocol=mqtt.MQTTv5)
    client.max_queued_messages_set(MAX_QUEUED)
    client.will_set(STATUS_TOPIC, "offline", qos=1, retain=True)

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            log.error(kv("connect_failed", reason=str(reason_code)))
            return
        # (Re)subscribe and announce on every connect, so a reconnect restores both.
        client.subscribe(SUBSCRIPTION, qos=1)
        client.publish(STATUS_TOPIC, "online", qos=1, retain=True)
        log.info(kv("connected", subscribed=SUBSCRIPTION, session_present=flags.session_present))

    def on_disconnect(client, userdata, flags, reason_code, properties):
        log.warning(kv("disconnected", reason=str(reason_code)))

    last_report = {"t": time.monotonic()}

    def on_message(client, userdata, msg):
        # pipeline.process never raises: a bug quarantines the message (stage=internal).
        outgoing = pipeline.process(msg.topic, msg.payload, datetime.now(timezone.utc))
        for o in outgoing:
            send(client, o)
        if time.monotonic() - last_report["t"] >= 60:          # once a minute, if anything was skipped
            counts = pipeline.take_skipped()
            if counts:
                log.info(kv("optional_fields_skipped", last="60s", counts=counts,
                            why="optional in the device type, no point in the asset model"))
            last_report["t"] = time.monotonic()

    client.on_connect, client.on_disconnect, client.on_message = on_connect, on_disconnect, on_message

    def connect_properties() -> Properties:
        props = Properties(PacketTypes.CONNECT)
        props.SessionExpiryInterval = SESSION_EXPIRY
        return props

    def stop(*_):
        client.publish(STATUS_TOPIC, "offline", qos=1, retain=True)
        client.disconnect()
    signal.signal(signal.SIGTERM, stop)                     # docker compose stop

    host, port = os.getenv("BROKER_HOST", "localhost"), int(os.getenv("BROKER_PORT", "1883"))
    log.info(kv("connecting", host=host, port=port))
    # Don't fail if the broker isn't up yet... (clean_start=False: always resume our session)
    client.connect_async(host, port, clean_start=False, properties=connect_properties())
    try:
        client.loop_forever(retry_first_connection=True)    # ...keep trying, and reconnect if it drops
    except KeyboardInterrupt:
        stop()


if __name__ == "__main__":
    main()
