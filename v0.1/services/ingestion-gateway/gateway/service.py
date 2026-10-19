"""
The running ingestion gateway: connects to the MQTT broker and runs the pipeline.

    python -m gateway.service          (settings from environment variables, below)

What it does:
  - subscribes to  raw/#  (QoS 1)
  - for each message, runs gateway/pipeline.py and publishes the results
  - announces itself on  dt/v1/status/ingestion_gateway  (online, with "offline" as Last Will)

Not losing data when something restarts (the "small buffer" in v0.1/README.md):
  - Broker down: paho keeps QoS 1 messages it couldn't send yet and sends them after it
    reconnects (paho-mqtt 2.1.0, Client.publish). Capped by MAX_QUEUED so memory can't run away.
  - Gateway down: the gateway uses a persistent session (clean_session=False), so the broker
    keeps raw QoS 1 messages for it while it's away (Mosquitto: max_queued_messages, default
    1000 per client) and delivers them when it's back.

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
  - Mosquitto max_queued_messages, persistent clients:  https://mosquitto.org/man/mosquitto-conf-5.html
  - Last Will, retained status, QoS 1, persistent sessions:  MQTT spec
      https://docs.oasis-open.org/mqtt/mqtt/v5.0/os/mqtt-v5.0-os.html
  - Topics and status rules:  v0.1/contracts/topics.md
"""
from __future__ import annotations

import json
import logging
import os
import signal
from datetime import datetime, timezone
from pathlib import Path

import paho.mqtt.client as mqtt

from .mapper import Mapper
from .pipeline import Pipeline, kv

CLIENT_ID = "ingestion_gateway"                        # lowercase + "_" only (topics.md rule 2)
STATUS_TOPIC = f"dt/v1/status/{CLIENT_ID}"
SUBSCRIPTION = "raw/#"
MAX_QUEUED = 10_000                                    # outgoing messages held while the broker is away

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


def build_pipeline() -> Pipeline:
    model_dir = Path(os.getenv("MODEL_DIR", Path(__file__).resolve().parents[3]))
    mapper = Mapper.from_folder(model_dir, enabled=parse_enabled(os.getenv("GATEWAY_ENABLED", "")))
    for note in mapper.report:
        log.info(kv("mapper_note", note=note))
    log.info(kv("mapper_loaded", model_dir=str(model_dir), field_mappings=len(mapper)))
    return Pipeline(mapper, site=os.getenv("GATEWAY_SITE", "site1"))


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(message)s")
    pipeline = build_pipeline()     # a broken model or mapping stops us here, before connecting

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=CLIENT_ID, clean_session=False)
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

    def on_message(client, userdata, msg):
        try:
            outgoing = pipeline.process(msg.topic, msg.payload, datetime.now(timezone.utc))
        except Exception:                                   # a bug must not stop the gateway
            log.exception(kv("pipeline_error", topic=msg.topic))
            return
        for o in outgoing:
            client.publish(o.topic, json.dumps(o.payload), qos=o.qos, retain=o.retain)

    client.on_connect, client.on_disconnect, client.on_message = on_connect, on_disconnect, on_message

    def stop(*_):
        client.publish(STATUS_TOPIC, "offline", qos=1, retain=True)
        client.disconnect()
    signal.signal(signal.SIGTERM, stop)                     # docker compose stop

    host, port = os.getenv("BROKER_HOST", "localhost"), int(os.getenv("BROKER_PORT", "1883"))
    log.info(kv("connecting", host=host, port=port))
    client.connect_async(host, port)          # don't fail if the broker isn't up yet...
    try:
        client.loop_forever(retry_first_connection=True)    # ...keep trying, and reconnect if it drops
    except KeyboardInterrupt:
        stop()


if __name__ == "__main__":
    main()
