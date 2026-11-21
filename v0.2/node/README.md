# dt-node

Runs on each device that has sensors plugged in (a Pi Zero, Pi 4, Pi 5). Reads them and sends
their readings to the broker. Nothing else: checking and interpreting is the gateway's job.

```
sensors ──► one thread per sensor ──► outbox (SQLite file) ──► broker ──► gateway
                                      kept until the broker confirms each message
```

| File | What |
|---|---|
| `dtnode/service.py` | The running node: sensor threads, the sender, online/offline status |
| `dtnode/health.py` | The heartbeat on `dt/v1/health/{name}` every 30 s: which sensors are reading, outbox size and drops |
| `dtnode/outbox.py` | Readings wait here until the broker confirms them; survives power cuts and outages |
| `dtnode/config.py` | Reads `node.toml` (what this device has); the password comes from env `MQTT_PASSWORD` |
| `dtnode/reading.py` | The message format (the same as dt-edge's, which the gateway reads) |
| `dtnode/adapters/` | One file per sensor type. Now: `simulated`, `csv` (replays a recorded run). Real sensors come from dt-edge |

**Light by design:** one required package (`paho-mqtt`); SQLite, TOML and threads are part of
Python. A sensor's own libraries are needed only on nodes that have that sensor.

**Run it** (laptop):
```
pip install -r requirements-dev.txt
python -m pytest -q
python -m dtnode.service node.toml          # with MQTT_PASSWORD set
```
In the dev setup: `docker compose --profile node up -d` (uses `dev/node.dev.toml`).

**A new device:** copy `node.example.toml` to `node.toml`, list its sensors, give it a `name`.
That name must be in the broker's `MQTT_DEVICES`, and the gateway needs a binding for it
(`gateway/model/mappings/bindings/`), which says which asset its readings belong to.
