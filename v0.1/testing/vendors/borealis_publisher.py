"""
Fake vendor "Borealis": the SAME kind of unit as Acme, but a different format.

What makes Borealis different from Acme (on purpose):
  - temperature already in Celsius, but labelled "C"
  - time as an ISO string with a local UTC offset (+01:00), not epoch ms
  - a list of readings, each with its own name, unit and time
  - mode in capitals inside a separate "status" block (HEATING/COOLING)
  - humidity again, which is NOT in the asset model yet -> quarantine

Publishes to:  raw/borealis/<device_slug>/data
Status topic:  dt/v1/status/<client_id>   (online, with "offline" as Last Will)
"""
import json
import math
import os
import random
import time
from datetime import datetime, timedelta, timezone

import paho.mqtt.client as mqtt

BROKER_HOST = os.getenv("BROKER_HOST", "localhost")
BROKER_PORT = int(os.getenv("BROKER_PORT", "1883"))
DEVICE_ID = os.getenv("DEVICE_ID", "site4-hvac_01")
INTERVAL_S = float(os.getenv("INTERVAL_S", "5"))

# Topic levels must be lowercase letters, numbers and "_" (see contracts/topics.md),
# so the vendor's own ID is turned into a "slug": ACME-HVAC-0001 -> acme_hvac_0001
DEVICE_SLUG = DEVICE_ID.lower().replace("-", "_")
CLIENT_ID = DEVICE_SLUG
TOPIC = f"raw/borealis/{DEVICE_SLUG}/data"
STATUS_TOPIC = f"dt/v1/status/{CLIENT_ID}"

LOCAL_TZ = timezone(timedelta(hours=1))  # Borealis kit reports UK summer time


def simulate(t):
    temp_c = 21 + 3 * math.sin(2 * math.pi * t / 60) + random.uniform(-0.5, 0.5)
    humidity = 55 - 2 * math.sin(2 * math.pi * t / 60) + random.uniform(-1, 1)
    mode = "heat" if temp_c < 21 else "cool"
    return temp_c, humidity, mode


def to_borealis_payload(temp_c, humidity, mode):
    """Turn clean values into Borealis's native format."""
    now = datetime.now(LOCAL_TZ).isoformat(timespec="seconds")  # e.g. 2026-10-14T13:00:00+01:00
    return {
        "site": "site4",
        "unit": DEVICE_ID,
        "readings": [
            {"metric": "temperature", "value": round(temp_c, 2), "unit": "C", "time": now},
            {"metric": "humidity", "value": round(humidity, 1), "unit": "%", "time": now},
        ],
        "status": {"mode": "HEATING" if mode == "heat" else "COOLING"},
    }


def main():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=CLIENT_ID)
    client.will_set(STATUS_TOPIC, "offline", qos=1, retain=True)
    client.connect(BROKER_HOST, BROKER_PORT)
    client.loop_start()
    client.publish(STATUS_TOPIC, "online", qos=1, retain=True)
    print(f"[borealis] publishing to {TOPIC} every {INTERVAL_S}s")

    t = 0.0
    try:
        while True:
            payload = to_borealis_payload(*simulate(t))
            client.publish(TOPIC, json.dumps(payload), qos=1)
            print(f"[borealis] {payload}")
            t += INTERVAL_S
            time.sleep(INTERVAL_S)
    except KeyboardInterrupt:
        pass
    finally:
        client.publish(STATUS_TOPIC, "offline", qos=1, retain=True)
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
