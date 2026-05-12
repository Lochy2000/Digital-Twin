# MQTT Layer
 
The communication backbone of the digital twin pipeline. This layer handles all message passing between the simulated sensor, the broker, and any downstream consumers (storage, processing, dashboard).
 
---
 
## What is MQTT?
 
MQTT (Message Queuing Telemetry Transport) is a lightweight publish/subscribe messaging protocol designed for IoT and real-time data scenarios.
 
Rather than components talking directly to each other, everything connects to a central **broker**. Components either **publish** messages to a topic, or **subscribe** to receive them. The broker routes messages between them.
 
```
publisher.py  →→  [Mosquitto broker]  →→  subscriber.py
  (sensor)           port 1883            (pipeline consumer)
```
 
No component knows about the others — they only know the broker address and topic name. This is what makes the architecture loosely coupled and easy to extend.
 
---
 
## Components
 
| File | Role |
|---|---|
| `docker-compose.yml` | Runs the Mosquitto broker in a Docker container |
| `mosquitto.conf` | Broker configuration — port and auth settings |
| `publisher.py` | Simulates an HVAC sensor, publishes readings every 3s |
| `subscriber.py` | Subscribes to the sensor topic and prints messages |
 
---
 
## Topic Structure
 
```
asset/hvac_01/telemetry
```
 
Topics use `/` as a hierarchy separator. This naming convention means you can:
 
- Subscribe to `asset/#` to receive messages from **all** assets
- Subscribe to `asset/hvac_01/#` to receive **everything** from one asset
- Add more asset types later (`asset/boiler_01/telemetry`) with zero changes to the broker
---
 
## Message Format
 
Each published message is a JSON object:
 
```json
{
  "asset_id": "hvac_01",
  "timestamp": "2026-05-11T15:20:37+00:00",
  "temperature_c": 19.4,
  "humidity_pct": 55.45,
  "mode": "heating"
}
```
 
---
 
## How to Run
 
### Prerequisites
 
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running
- Python 3.x installed
---
 
### Step 1 — Create and activate the virtual environment
 
```bash
# Create the environment (first time only)
python -m venv venv
 
# Activate — Windows
venv\Scripts\activate
 
# Activate — Mac/Linux
source venv/bin/activate
```
 
You will see `(venv)` at the start of your terminal line when active.
 
```bash
# Install dependencies
pip install paho-mqtt
```
 
---
 
### Step 2 — Start the broker (Terminal 1)
 
```bash
docker-compose up
```
 
You should see:
 
```
mosquitto version 2.1.2 running
Opening ipv4 listen socket on port 1883
```
 
The broker is now running and waiting for connections.
 
---
 
### Step 3 — Start the subscriber (Terminal 2)
 
```bash
# Activate venv first if not already active
venv\Scripts\activate
 
python subscriber.py
```
 
The subscriber connects and waits. No messages yet — that is expected.
 
---
 
### Step 4 — Start the publisher (Terminal 3)
 
```bash
# Activate venv first if not already active
venv\Scripts\activate
 
python publisher.py
```
 
Simulated HVAC readings will now publish every 3 seconds. Switch to Terminal 2 and you will see them arrive in real time:
 
```
┌─ [15:20:37] message received
│  asset     : hvac_01
│  sensor ts : 2026-05-11T15:20:37+00:00
│  temp      : 19.4 °C
│  humidity  : 55.45 %
│  mode      : heating
└─────────────────────────────────
```
 
---
 
## What the Broker Logs Mean
 
```
New connection from 172.22.0.1:35760 as auto-9A54C3D8... (p4, c1, k60)
```
 
| Part | Meaning |
|---|---|
| `172.22.0.1` | Docker's internal gateway — how your local machine appears to the container |
| `auto-9A54C3D8...` | Auto-generated client ID (publisher or subscriber) |
| `p4` | MQTT protocol version 4 |
| `c1` | Clean session — no message history carried over on reconnect |
| `k60` | Keepalive ping every 60 seconds to maintain the connection |
 
---
 
## Things to Try
 
**Kill the publisher and restart it** — the subscriber stays alive and reconnects automatically.
 
**Change the subscriber topic to `asset/#`** — it will now receive messages from any asset. Add a second publisher for `hvac_02` and both streams arrive in one subscriber.
 
**Watch the temperature cycle** — the publisher uses a sine wave so temperature oscillates realistically between ~18°C and ~24°C, flipping between heating and cooling mode.
 
---
 
## Next Steps
 
This layer handles communication only. The natural extensions are:
 
1. **Storage** — replace the `print` in `subscriber.py` with a write to InfluxDB
2. **Processing** — a third script that subscribes, computes (e.g. anomaly detection, rolling average), and re-publishes to a new topic
3. **Dashboard** — Grafana reading from InfluxDB to visualise the live data stream
4. **Managed broker** — swap Mosquitto for HiveMQ Cloud or AWS IoT Core and compare cost and deployment complexity