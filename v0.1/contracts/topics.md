# MQTT topics: v0.1

Where each kind of message lives on the broker, who publishes it, and who listens.
The message *shape* is in `canonical_message.schema.json`; this file covers the *addresses*.

---

## Quick primer

- A **topic** is a text address like `dt/v1/telemetry/site1/unit1/zone_air_temp`. The `/` splits it into **levels**.
- Publishers send to an exact topic. Subscribers can use **wildcards**, but only when subscribing:
  - `+` matches **one** level: `dt/v1/telemetry/site1/+/zone_air_temp` gets the zone temperature from every unit at site1.
  - `#` matches **everything below** a point, and must be last: `dt/v1/telemetry/site1/unit1/#` gets every point on unit1.
- Topics starting with `$` are reserved for the broker (e.g. `$SYS/...` for its own stats). We never publish to them.

---

## Naming rules

These follow HiveMQ's [MQTT topic best practices](https://www.hivemq.com/blog/mqtt-essentials-part-5-mqtt-topics-best-practices/):

1. **No leading slash.** Write `dt/v1/...`, not `/dt/v1/...`; a leading slash creates an empty first level.
2. **Lowercase ASCII, numbers and `_` only.** No spaces or special characters, so topics are easy to type, read and debug.
3. **One data stream per topic.** Each point gets its own topic rather than sharing a generic one.
4. **A version in the path (`v1`).** If topics ever need restructuring, `v2` can run alongside `v1` during a switch-over.
5. **The sender's identity in raw topics.** This lets the broker restrict each device to its own topics (see *Access rules* below).
6. **Message class first.** Putting `telemetry`, `twin`, `alerts` and so on near the start lets a service subscribe to a whole class with one wildcard, e.g. the historian uses `dt/v1/telemetry/#`.

---

## The topic map

### In use from step 2

| Topic | What's on it | Published by | Subscribed by | QoS | Retained |
|---|---|---|---|---|---|
| `raw/{source}/{device}/...` | Device data in its **own native format** (not canonical) | Devices, test vendors, sim plant | Ingestion gateway only | 0 or 1 | No |
| `dt/v1/telemetry/{site}/{equipment}/{point}` | **Canonical messages**, one reading each | Ingestion gateway only | Twin, detection, historian, API | 1 | No |
| `dt/v1/quarantine/{source}` | Readings the gateway couldn't process, plus the reason (shape: `quarantine_message.schema.json`) | Ingestion gateway only | Historian (to log them), engineer for debugging | 1 | No |
| `dt/v1/status/{client_id}` | `online` / `offline` for each service and device | Each client (`offline` is sent automatically by the broker, see below) | API, detection | 1 | **Yes** |

### Reserved for later steps (names only, not built yet)

| Topic | What's on it | Published by | Retained |
|---|---|---|---|
| `dt/v1/twin/{site}/{equipment}/state` | Latest twin state (estimated temperatures, data state LIVE / COASTING / STALE) | Twin engine | **Yes** |
| `dt/v1/twin/{site}/{equipment}/residual` | Prediction minus measurement, per point | Twin engine | No |
| `dt/v1/alerts/{site}` | Alert events (raised, acknowledged, cleared) | Detection | No |
| `dt/v1/scenario/req` | What-if run requests (MQTT 5 request/response) | API gateway | No |
| `dt/v1/scenario/res/{run_id}` | What-if run results | Scenario worker | No |

---

## How a canonical topic is built

The canonical topic comes straight from the message's `point` ID: swap the `.` for `/` and put the site in front.

```
point  =  unit1.zone_air_temp           (from the asset model)
site   =  site1                         (from gateway config)
topic  =  dt/v1/telemetry/site1/unit1/zone_air_temp
```

The site is in the **topic** but not in the **point ID**, because there is only one site in v0.1. If a second site arrives, this is the place to revisit (see the open question in `NOTES.md`).

Example subscriptions:

| I want… | Subscribe to |
|---|---|
| Everything canonical | `dt/v1/telemetry/#` |
| Every point on unit1 | `dt/v1/telemetry/site1/unit1/#` |
| Zone temperature from every unit | `dt/v1/telemetry/site1/+/zone_air_temp` |
| Everything rejected by the gateway | `dt/v1/quarantine/#` |
| Raw data from the acme test vendor | `raw/acme/#` |

---

## Why raw and canonical are kept apart

```
device ──► raw/acme/hvac_01/telemetry ──► [ingestion gateway] ──► dt/v1/telemetry/site1/unit1/zone_air_temp ──► everyone else
                                                              └──► dt/v1/quarantine/acme   (if it can't be processed)
```

- **Only the gateway reads `raw/...`, and only the gateway writes `dt/v1/telemetry/...`.** That is the "front door" rule: nothing downstream ever sees a device's native format.
- If a device can't choose its own topic (some vendor kit has fixed topics), the MQTT adapter can subscribe to that fixed topic instead. The `raw/` prefix is the default, not a hard requirement.

### Raw formats known so far (added in step 2f)

| Source | Topic | Payload | Format defined by |
|---|---|---|---|
| `tasmota` | `raw/tasmota/{device}/tele/SENSOR` (also `STATE`, `LWT`) | Tasmota's own JSON | Tasmota. The device is set to this topic with `FullTopic raw/tasmota/%topic%/%prefix%/` ([Commands](https://tasmota.github.io/docs/Commands/)) |
| `modbus` | `raw/modbus/{device}/registers` | `{"time": "<UTC>Z", "registers": {"InputRegister:12": [w1, w2], ...}}`: the 16-bit words read, untouched | **Us**: the Modbus poller (later step) publishes this. Decoded in `gateway/decoders/modbus.py` |
| `acme`, `borealis` | `raw/acme/{device}/telemetry`, `raw/borealis/{device}/data` | Made-up test formats | `testing/vendors/` |

---

## QoS and retained messages

**QoS (Quality of Service)** is how hard the broker tries to deliver a message:
- **0:** at most once. Fire and forget; may be lost.
- **1:** at least once. Delivery is retried until acknowledged, so a message may arrive twice.
- **2:** exactly once. Slowest, and not needed here.

We use **QoS 1** for canonical data. Duplicates are harmless because storage can ignore a second copy with the same `point` + `sensor_time`.

**Retained** means the broker keeps the *last* message on that topic and hands it to anyone who subscribes later. It suits "current state" topics (`status`, twin `state`), but not readings: a new subscriber shouldn't receive an old reading as if it were fresh.

---

## Online / offline status (Last Will)

When a client connects, it can register a **Last Will** message with the broker: "if I drop off without saying goodbye, publish this for me". Each service and device will:
1. register a Last Will of `offline` on `dt/v1/status/{client_id}` (retained);
2. publish `online` to the same topic (retained) once connected.

So anyone can see at a glance what's up and what's down, even after a crash. This feeds the LIVE / COASTING / STALE data state later.

---

## Scaling: shared subscriptions

If one historian can't keep up later, several copies can share the work using an MQTT 5 **shared subscription**:

```
$share/historians/dt/v1/telemetry/#
```

Every client that subscribes with the same group name (`historians`) takes turns: the broker gives each message to just one of them ([HiveMQ – Shared subscriptions](https://www.hivemq.com/blog/mqtt5-essentials-part7-shared-subscriptions/)). The topic names don't change. Not needed for v0.1, but the naming already allows it.

---

## Access rules (draft)

Mosquitto can limit which topics each login can read or write, using an **ACL file** (access control list). The rules below describe the intent; the real file is written in the deployment step.

```
# Each device may only write its own raw topics. %u = its login name.
pattern write raw/%u/#
pattern write dt/v1/status/%u

user ingestion-gateway
topic read      raw/#
topic write     dt/v1/telemetry/#
topic write     dt/v1/quarantine/#

user historian
topic read      dt/v1/#

user twin-engine
topic read      dt/v1/telemetry/#
topic write     dt/v1/twin/#
```

This makes the front-door rule enforceable, not just a convention: a device *cannot* publish fake canonical data, because the broker refuses it. `pattern` and `%u` are explained in the [mosquitto.conf docs](https://mosquitto.org/man/mosquitto-conf-5.html).
