import json
from datetime import datetime, timezone
import paho.mqtt.client as mqtt
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS
import os

# --- Config ---
BROKER_HOST = os.getenv("BROKER_HOST", "localhost")
BROKER_PORT = 1883
TOPIC = "asset/hvac_01/telemetry"

INFLUX_URL = os.getenv("INFLUX_URL", "http://localhost:8086")
INFLUX_TOKEN  = "my-super-secret-token"
INFLUX_ORG    = "dt-org"
INFLUX_BUCKET = "hvac"

# --- InfluxDB client ---
influx = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
write_api = influx.write_api(write_options=SYNCHRONOUS)

def write_to_influx(payload: dict):
    point = (
        Point("hvac_telemetry")
        .tag("asset_id", payload.get("asset_id", "unknown"))
        .tag("mode", payload.get("mode", "unknown"))
        .field("temperature_c", float(payload["temperature_c"]))
        .field("humidity_pct", float(payload["humidity_pct"]))
        .time(payload.get("timestamp"), write_precision="s")
    )
    write_api.write(bucket=INFLUX_BUCKET, record=point)
    print(f"[influx] written — temp: {payload['temperature_c']}°C  humidity: {payload['humidity_pct']}%")

def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print(f"[broker] connected to {BROKER_HOST}:{BROKER_PORT}")
        client.subscribe(TOPIC)
        print(f"[broker] subscribed to: {TOPIC}")
        print("[storage] waiting for messages...\n")
    else:
        print(f"[broker] connection failed — code {rc}")

def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
        write_to_influx(payload)
    except (json.JSONDecodeError, KeyError) as e:
        print(f"[error] could not process message: {e}")

def on_disconnect(client, userdata, rc, properties=None, reasonCode=None):
    print("\n[broker] disconnected — will reconnect...")

def main():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = on_disconnect
    client.reconnect_delay_set(min_delay=1, max_delay=10)

    print("[storage] connecting to broker...")
    client.connect(BROKER_HOST, BROKER_PORT)
    client.loop_forever()

if __name__ == "__main__":
    main()