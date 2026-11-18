# testing/vendors/: developer notes

Two fake equipment vendors used to test the ingestion gateway. They pretend to be **the same heat/cool unit** from two different manufacturers, each with its own message format. If the gateway turns both into identical canonical messages, the adapter idea works.

Newest entry at the bottom.

---

## 2026-10-14 · Step 2a: vendors fixed and moved into v0.1

### What I added

| File | Purpose |
|---|---|
| `acme_publisher.py` | Vendor "Acme": Fahrenheit, epoch-ms time, numeric mode |
| `borealis_publisher.py` | Vendor "Borealis": Celsius list, local-time strings, mode in capitals |
| `requirements.txt` | `paho-mqtt` (the MQTT client library), pinned to 2.1.0 like the root prototype |
| `Dockerfile` | One image for both; `docker-compose.yml` picks which script runs |
| `../../docker-compose.yml` | v0.1's own stack: broker + one vendor at a time |
| `../../broker/mosquitto.conf` | Broker config (anonymous for now, see below) |

### What was wrong in the root versions

Both root scripts defined a vendor format function but never called it. They published the old generic payload, so "two vendors" were really one. Here, each main loop calls its own `to_acme_payload` / `to_borealis_payload`.

### The two formats side by side

Same moment, same room, two vendors:

```json
// raw/acme/acme_hvac_0001/telemetry
{"deviceId": "ACME-HVAC-0001", "ts": 1792006418428, "tempF": 70.4, "rh": 54.0, "op_state": 2}
```

```json
// raw/borealis/site4_hvac_01/data
{"site": "site4", "unit": "site4-hvac_01",
 "readings": [{"metric": "temperature", "value": 21.29, "unit": "C", "time": "2026-10-14T20:33:38+01:00"},
              {"metric": "humidity",    "value": 55.6,  "unit": "%", "time": "2026-10-14T20:33:38+01:00"}],
 "status": {"mode": "COOLING"}}
```

What the gateway will have to deal with:

| | Acme | Borealis | Canonical target |
|---|---|---|---|
| Temperature | `tempF` in °F | `readings[].value`, unit `"C"` | `DEG_C` |
| Time | epoch **milliseconds** | ISO string with `+01:00` | UTC ISO ending in `Z` |
| Mode | `op_state`: 1 / 2 / 3 | `status.mode`: `HEATING` / `COOLING` | `heat` / `cool` / `off` |
| Shape | flat object | list of readings | one message per reading |
| Humidity | `rh` | `readings[]` | **not in the asset model**, so it should go to quarantine |

The humidity case is deliberate: it is the first real test of "unknown point goes to quarantine, nothing breaks".

### Decisions

**1. Each vendor's device ID becomes a "slug" in its topics.**
- *Why:* topic levels must be lowercase letters, numbers and `_` (rule 2 in `contracts/topics.md`). `ACME-HVAC-0001` becomes `acme_hvac_0001`. The vendor's original ID is kept inside the payload, as a real device would send it.

**2. Each vendor announces online / offline on `dt/v1/status/<client_id>`.**
- It sets a Last Will of `offline` (retained), then publishes `online` (retained) once connected.
- *Tested:* a subscriber that connected later still received the last known status, because retained messages work as intended.

**3. Run one vendor at a time (compose profiles).**
- *Why:* both pretend to be the same physical unit. Running both at once would put two competing temperature streams on one point.
- Swapping `--profile acme` for `--profile borealis` is the actual test: **the vendor changes, and nothing downstream should.**

**4. The broker allows anonymous connections for now.**
- *Why:* to keep the first runs simple. Logins and the access rules drafted in `contracts/topics.md` come in the deployment step. This is written in the config file too, so it isn't forgotten.

### How I tested it

I ran both scripts against a small local test broker (amqtt) and subscribed to `raw/#` and `dt/v1/status/#`. Both formats arrived on the expected topics, statuses showed `online`, then `offline` when they stopped.

### Try it yourself

```bash
cd v0.1
# stop the root prototype first, it also uses port 1883
docker compose --profile acme up --build

# in a second terminal: watch everything on the broker
docker compose exec mosquitto mosquitto_sub -v -t "raw/#" -t "dt/v1/#"
```

Then stop it, run `--profile borealis` instead, and compare the two formats.

### Noticed while doing this

- The asset model has `unit1.mode_cmd` (a `Mode_Command`), but what a device *reports* is its current mode, which Brick calls a `Mode_Status`. The vendors report status, not commands. I'll add a `unit1.mode_status` point to the asset model when building the mapper (step 2b), rather than wrongly mapping status onto the command point.

### Next: step 2b, mapper

Build the part of the gateway that reads `dtteo_asset_model.ttl` and answers: "this vendor's `tempF` on this device is which point ID?"

---

## 2026-10-16 · Step 2e: what these two are, and what they are not

**Acme and Borealis are made-up vendors.** Each is a small script that pretends to be a heat/cool unit and publishes in its own invented format. They exist only to prove one thing: two different formats can end up as identical canonical messages.

They are **not** what the system is built around:
- The onboarding design (`mappings/DESIGN.md`) is also tested against two **real, published** formats: **Tasmota** (open-source firmware for the ESP8266, JSON over MQTT) and the **Eastron SDM120** electricity meter (Modbus registers). See `mappings/types/`.
- Acme and Borealis are now described the same way as the real devices: one device type each (`mappings/types/acme_hvac.ttl`, `borealis_hvac.ttl`) plus one binding each (`mappings/bindings/site1.ttl`).
- Because both pretend to be **the same unit**, only one may be enabled at a time. Acme is on; Borealis is off. Swap the `dtteo:enabled` lines to switch, matching the compose profiles here.

When real equipment arrives, these scripts can be deleted without touching the gateway.
