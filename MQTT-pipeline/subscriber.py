import json
from datetime import datetime, timezone
import paho.mqtt.client as mqtt

# --- Config ---
BROKER_HOST = "localhost"
BROKER_PORT = 1883
TOPIC = "asset/hvac_01/telemetry"

def format_message(payload: dict) -> str:
    received_at = datetime.now(timezone.utc).strftime("%H:%M:%S")
    sensor_ts = payload.get("timestamp", "unknown")
    asset_id = payload.get("asset_id", "unknown")
    temp = payload.get("temperature_c", "—")
    humidity = payload.get("humidity_pct", "—")
    mode = payload.get("mode", "—")

    return (
        f"\n┌─ [{received_at}] message received"
        f"\n│  asset     : {asset_id}"
        f"\n│  sensor ts : {sensor_ts}"
        f"\n│  temp      : {temp} °C"
        f"\n│  humidity  : {humidity} %"
        f"\n│  mode      : {mode}"
        f"\n└─────────────────────────────────"
    )

def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print(f"[broker] connected to {BROKER_HOST}:{BROKER_PORT}")
        client.subscribe(TOPIC)
        print(f"[broker] subscribed to topic: {TOPIC}")
        print("[subscriber] waiting for messages...\n")
    else:
        print(f"[broker] connection failed with code {rc}")

def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
        print(format_message(payload))
    except json.JSONDecodeError:
        print(f"[error] could not parse message: {msg.payload}")

def on_disconnect(client, userdata, rc, properties=None, reasonCode=None):
    print("\n[broker] disconnected. will attempt to reconnect...")

def main():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = on_disconnect

    # auto-reconnect on dropped connection
    client.reconnect_delay_set(min_delay=1, max_delay=10)

    print("[subscriber] connecting to broker...")
    client.connect(BROKER_HOST, BROKER_PORT)
    client.loop_forever()  # blocks here, handles reconnects automatically

if __name__ == "__main__":
    main()