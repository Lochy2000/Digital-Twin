import json
import time
import random
import math
from datetime import datetime, timezone
import paho.mqtt.client as mqtt

# --- Config ---
BROKER_HOST = "localhost"
BROKER_PORT = 1883
TOPIC = "asset/hvac_01/telemetry"
PUBLISH_INTERVAL = 3  # seconds

# --- Simulate realistic HVAC thermal behaviour ---
# Uses a sine wave as a base cycle (simulates heating/cooling cycle)
# with small random noise on top

def get_simulated_readings(t):
    # Base temperature oscillates between 18°C and 24°C over a slow cycle
    base_temp = 21 + 3 * math.sin(2 * math.pi * t / 60)
    temperature = round(base_temp + random.uniform(-0.5, 0.5), 2)

    # Humidity inversely loosely correlated with temperature
    base_humidity = 55 - 2 * math.sin(2 * math.pi * t / 60)
    humidity = round(base_humidity + random.uniform(-1, 1), 2)

    return temperature, humidity

def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print(f"[broker] connected to {BROKER_HOST}:{BROKER_PORT}")
        print(f"[broker] publishing to topic: {TOPIC}\n")
    else:
        print(f"[broker] connection failed with code {rc}")

def main():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect

    client.connect(BROKER_HOST, BROKER_PORT)
    client.loop_start()

    t = 0  # time counter drives the sine wave

    print("[publisher] starting HVAC sensor simulation...")

    try:
        while True:
            temperature, humidity = get_simulated_readings(t)

            payload = {
                "asset_id": "hvac_01",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "temperature_c": temperature,
                "humidity_pct": humidity,
                "mode": "heating" if temperature < 21 else "cooling"
            }

            client.publish(TOPIC, json.dumps(payload))
            print(f"[published] {payload}")

            t += PUBLISH_INTERVAL
            time.sleep(PUBLISH_INTERVAL)

    except KeyboardInterrupt:
        print("\n[publisher] stopped.")
        client.loop_stop()
        client.disconnect()

if __name__ == "__main__":
    main()