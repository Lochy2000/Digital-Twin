"""
The running ingestion gateway: connects to the MQTT broker and runs the pipeline.

    python -m gateway.service          (settings from environment variables: gateway/settings.py)

What it does:
  - subscribes to  raw/#  (QoS 1)
  - for each message, runs gateway/pipeline.py and publishes the results
  - announces itself on  dt/v1/status/ingestion_gateway  (online, with "offline" as Last Will)

Protocol: MQTT 5 (step 2j). v0.1's design leans on MQTT 5 features (shared subscriptions,
request/response), so the gateway speaks it too. In MQTT 5, "keep my session while I'm away"
is clean_start=False PLUS a Session Expiry Interval above 0; with no interval the session
ends at disconnect (HiveMQ, MQTT 5 Essentials part 4).

Not losing data when something restarts (the "small buffer" in v0.1/README.md):
  - Gateway crashes mid-message (v0.2 step D): a raw message is acknowledged only after the broker
    has confirmed every output made from it (gateway/acks.py). Until then the broker still holds
    it and sends it again after a restart.
  - Broker down: paho keeps QoS 1 messages it couldn't send yet and sends them after it
    reconnects (paho-mqtt 2.1.0, Client.publish). Capped by MAX_QUEUED so memory can't run away;
    if the cap is hit, paho refuses the message (MQTT_ERR_QUEUE_SIZE) and we log an ERROR.
    With manual acks this shouldn't happen: the broker sends at most RECEIVE_MAX unacknowledged
    raw messages, so at most RECEIVE_MAX x (outputs per message) can be waiting.
  - Gateway down: the broker keeps raw QoS 1 messages for our session (SESSION_EXPIRY) and
    delivers them when we're back. How many it keeps is the broker's max_queued_messages, and
    whether they survive a BROKER restart is its persistence setting (broker/mosquitto.conf).

Health (v0.2 step D2): a heartbeat every 30 s on dt/v1/health/ingestion_gateway and in
HEALTH_FILE, read by Docker's HEALTHCHECK (dtteo_common/health.py). Unhealthy when:
  - not connected, or the broker has confirmed nothing for 75 s (connection or loop stuck);
  - a raw message has waited over STUCK_AFTER seconds for its outputs to be confirmed.

Settings: gateway/settings.py (read and checked once at start-up).

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
import signal
import threading
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties

from dtteo_common.health import BrokerLink, Heartbeat
from dtteo_common.mapper import Mapper

from .acks import AckTracker
from .decoders import load_plugins
from .pipeline import Outgoing, Pipeline, kv
from .settings import Settings, SettingsError, parse_enabled  # noqa: F401  (parse_enabled: tests)

CLIENT_ID = "ingestion_gateway"                        # lowercase + "_" only (topics.md rule 2)
STATUS_TOPIC = f"dt/v1/status/{CLIENT_ID}"
SUBSCRIPTION = "raw/#"
MAX_QUEUED = 10_000                                    # outgoing messages held while the broker is away
SESSION_EXPIRY = 7 * 24 * 3600                         # seconds the broker keeps our session while we're away
RECEIVE_MAX = 100                                      # most unacknowledged raw messages the broker may send us
RECONNECT_MAX_S = 5                                    # paho's default backoff grows to 120 s (found in D2 test)
STUCK_AFTER = 60                                       # seconds a raw message may wait for its ack before we're "stuck"

log = logging.getLogger("gateway")


def send(client: mqtt.Client, o: Outgoing) -> int | None:
    """Publish one message. Returns its id if paho holds it (sent, or sent after a reconnect),
    None if it couldn't even be queued (it is lost, and logged)."""
    info = client.publish(o.topic, json.dumps(o.payload), qos=o.qos, retain=o.retain)
    if info.rc in (mqtt.MQTT_ERR_SUCCESS, mqtt.MQTT_ERR_NO_CONN):
        return info.mid
    if info.rc == mqtt.MQTT_ERR_QUEUE_SIZE:
        # paho refuses new messages once MAX_QUEUED are waiting: this one is LOST.
        log.error(kv("publish_dropped", topic=o.topic, reason="outgoing queue full",
                     max_queued=MAX_QUEUED, point=o.payload.get("point")))
    elif info.rc not in (mqtt.MQTT_ERR_SUCCESS, mqtt.MQTT_ERR_NO_CONN):
        # NO_CONN is normal while reconnecting: paho keeps the message and sends it later.
        log.warning(kv("publish_problem", topic=o.topic, rc=mqtt.error_string(info.rc)))
    return None


def build_pipeline(settings: Settings | None = None) -> Pipeline:
    settings = settings or Settings.from_env()
    extra = []
    if settings.plugins:
        log.info(kv("plugins_loaded", folder=str(settings.plugins), decoders=load_plugins(settings.plugins)))
        extra = [settings.plugins / "mappings"]
    mapper = Mapper.from_folder(settings.model_dir, enabled=settings.enabled, extra_dirs=extra)
    for note in mapper.report:
        log.info(kv("mapper_note", note=note))
    log.info(kv("mapper_loaded", model_dir=str(settings.model_dir), field_mappings=len(mapper)))
    return Pipeline(mapper, site=settings.site)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        settings = Settings.from_env()          # every setting checked before anything starts
    except SettingsError as e:
        log.error(kv("settings_invalid", problems=str(e)))
        raise SystemExit(2)
    logging.getLogger().setLevel(settings.log_level)
    log.info(kv("settings", **settings.for_log()))
    pipeline = build_pipeline(settings)     # a broken model or mapping stops us here, before connecting

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=CLIENT_ID, protocol=mqtt.MQTTv5)
    client.max_queued_messages_set(MAX_QUEUED)
    client.reconnect_delay_set(min_delay=1, max_delay=RECONNECT_MAX_S)
    client.manual_ack_set(True)                             # we ack, once the outputs are safe (acks.py)
    tracker = AckTracker(client.ack)
    link = BrokerLink()
    received = {"n": 0}

    def status():
        problems = link.problems()
        wait = tracker.oldest_wait()
        if wait > STUCK_AFTER:
            problems.append(f"{tracker.pending} raw messages waiting for an ack, oldest {wait:.0f}s")
        return problems, {"received": received["n"], "acked": tracker.acked, "pending": tracker.pending}

    def publish_health(topic, text):
        if link.is_connected:           # not queued while away: an old heartbeat later would mislead
            client.publish(topic, text, qos=1, retain=True)

    heartbeat = Heartbeat(CLIENT_ID, status, publish_health, path=settings.health_file)
    if settings.mqtt_password:                              # the broker refuses anonymous clients
        client.username_pw_set(settings.mqtt_username, settings.mqtt_password)
    client.will_set(STATUS_TOPIC, "offline", qos=1, retain=True)

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            log.error(kv("connect_failed", reason=str(reason_code)))
            return
        link.connected()
        # Acks from the old connection aren't valid any more; the broker re-sends those messages.
        dropped = tracker.reconnected()
        if dropped:
            log.info(kv("unacked_dropped_on_reconnect", messages=dropped, why="broker sends them again"))
        # (Re)subscribe and announce on every connect, so a reconnect restores both.
        client.subscribe(SUBSCRIPTION, qos=1)
        client.publish(STATUS_TOPIC, "online", qos=1, retain=True)
        log.info(kv("connected", subscribed=SUBSCRIPTION, session_present=flags.session_present))

    def on_disconnect(client, userdata, flags, reason_code, properties):
        link.disconnected()
        log.warning(kv("disconnected", reason=str(reason_code)))

    last_report = {"t": time.monotonic()}

    def on_message(client, userdata, msg):
        # pipeline.process never raises: a bug quarantines the message (stage=internal).
        received["n"] += 1
        outgoing = pipeline.process(msg.topic, msg.payload, datetime.now(timezone.utc))
        # A failed send (None) can't be waited for; it was logged as lost. QoS 0 has no confirmation.
        mids = [mid for o in outgoing if (mid := send(client, o)) is not None and o.qos > 0]
        tracker.received(msg.mid, msg.qos, mids)
        if time.monotonic() - last_report["t"] >= 60:          # once a minute, if anything was skipped
            counts = pipeline.take_skipped()
            if counts:
                log.info(kv("optional_fields_skipped", last="60s", counts=counts,
                            why="optional in the device type, no point in the asset model"))
            last_report["t"] = time.monotonic()

    def on_publish(client, userdata, mid, reason_code, properties):
        link.confirmed()                                    # the broker is answering
        tracker.published(mid)                              # the broker has this output now

    client.on_connect, client.on_disconnect, client.on_message = on_connect, on_disconnect, on_message
    client.on_publish = on_publish

    def connect_properties() -> Properties:
        props = Properties(PacketTypes.CONNECT)
        props.SessionExpiryInterval = SESSION_EXPIRY
        props.ReceiveMaximum = RECEIVE_MAX                  # limits what can be waiting for an ack
        return props

    def stop(*_):
        heartbeat.stop()
        client.publish(STATUS_TOPIC, "offline", qos=1, retain=True)
        client.disconnect()
    # docker compose stop. The signal arrives on this thread, which is also paho's network
    # thread, possibly in the middle of paho's own bookkeeping; publishing from there crashed
    # ("OrderedDict mutated during iteration", D2 test). From another thread, paho's lock
    # makes the publish wait its turn.
    signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=stop, name="stop").start())

    host, port = settings.broker_host, settings.broker_port
    log.info(kv("connecting", host=host, port=port))
    # Don't fail if the broker isn't up yet... (clean_start=False: always resume our session)
    client.connect_async(host, port, clean_start=False, properties=connect_properties())
    heartbeat.start()                                       # reports "not connected" until we are
    try:
        client.loop_forever(retry_first_connection=True)    # ...keep trying, and reconnect if it drops
    except KeyboardInterrupt:
        stop()


if __name__ == "__main__":
    main()
