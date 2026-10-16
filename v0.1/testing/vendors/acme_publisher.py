"""
Fake vendor "Acme": a heat/cool unit that reports in its OWN format.

What makes Acme awkward (on purpose):
  - temperature in Fahrenheit            -> gateway must convert to DEG_C
  - time as epoch milliseconds           -> gateway must convert to UTC ISO time
  - mode as a number (1/2/3)             -> gateway must map to heat/cool/off
  - several readings in one message      -> gateway must split into one message each
  - humidity, which is NOT in the asset model yet -> should end up in quarantine

Publishes to:  raw/acme/<device_slug>/telemetry
Status topic:  dt/v1/status/<client_id>   (online, with "offline" as Last Will)
"""
import json
import math
import os
import random
import time

import paho.mqtt.client as mqtt

BROKER_HOST = os.getenv("BROKER_HOST", "localhost")
BROKER_PORT = int(os.getenv("BROKER_PORT", "1883"))
DEVICE_ID = os.getenv("DEVICE_ID", "ACME-HVAC-0001")
INTERVAL_S = float(os.getenv("INTERVAL_S", "3"))

# Topic levels must be lowercase letters, numbers and "_" (see contracts/topics.md),
# so the vendor's own ID is turned into a "slug": ACME-HVAC-0001 -> acme_hvac_0001
DEVICE_SLUG = DEVICE_ID.lower().replace("-", "_")
CLIENT_ID = DEVICE_SLUG
TOPIC = f"raw/acme/{DEVICE_SLUG}/telemetry"
STATUS_TOPIC = f"dt/v1/status/{CLIENT_ID}"

ACME_MODE_CODES = {"heat": 1, "cool": 2, "off": 3}  # Acme's own codes


def simulate(t):
    """Same simple sine-wave room as the old prototype, in Celsius."""
    temp_c = 21 + 3 * math.sin(2 * math.pi * t / 60) + random.uniform(-0.5, 0.5)
    humidity = 55 - 2 * math.sin(2 * math.pi * t / 60) + random.uniform(-1, 1)
    mode = "heat" if temp_c < 21 else "cool"
    return temp_c, humidity, mode


def to_acme_payload(temp_c, humidity, mode):
    """Turn clean values into Acme's native format."""
    return {
        "deviceId": DEVICE_ID,
        "ts": int(time.time() * 1000),               # epoch milliseconds
        "tempF": round(temp_c * 9 / 5 + 32, 1),       # Fahrenheit
        "rh": round(humidity, 1),                     # relative humidity %
        "op_state": ACME_MODE_CODES[mode],            # numeric mode
    }


def main():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=CLIENT_ID)
    # Last Will: if this client vanishes, the broker publishes "offline" for it.
    # qos 1 means it requires at a response. change to 0 if this doesnt matter
    client.will_set(STATUS_TOPIC, "offline", qos=1, retain=True)
    client.connect(BROKER_HOST, BROKER_PORT)
    client.loop_start()
    client.publish(STATUS_TOPIC, "online", qos=1, retain=True)
    print(f"[acme] publishing to {TOPIC} every {INTERVAL_S}s")

    t = 0.0
    try:
        while True:
            payload = to_acme_payload(*simulate(t))
            client.publish(TOPIC, json.dumps(payload), qos=1)
            print(f"[acme] {payload}")
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
