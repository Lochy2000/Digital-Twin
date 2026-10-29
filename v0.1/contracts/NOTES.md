# contracts/: developer notes

Working notes for the message contract. Everything for this build lives in `v0.1/`; the root folders (`mqtt-pipeline`, `storage`, `testing`) are the earlier prototype. Each entry records what changed, why, and what's still open. Newest entry at the bottom.

---

## 2026-10-14 · Step 1a: canonical message schema

### What I added

| File | Purpose |
|---|---|
| `canonical_message.schema.json` | The canonical message, written as a JSON Schema |
| `examples/valid/*.json` | Messages that **must** pass |
| `examples/invalid/*.json` | Messages that **must** fail, one mistake each |
| `check_examples.py` | Runs every example against the schema |
| `requirements.txt` | `jsonschema` library for the checker |

Run it:

```bash
pip install -r requirements.txt
python check_examples.py
```

### What a JSON Schema is (and why use one)

A JSON Schema is a JSON file that describes what another JSON message is allowed to look like: which fields are required, their types, and allowed values. Libraries in most languages can check a message against it.

I chose it over a Python class because:
- **It's language-neutral.** The ESP8266 firmware, Python services and a future React UI can all use the same file.
- **It's the contract itself.** Code can drift from documentation; this file *is* the rule.
- **It plugs into AsyncAPI later.** AsyncAPI, the standard for documenting MQTT topics, uses JSON Schema for message payloads, so this file can be reused as-is.

### The fields, and why each one is there

```json
{
  "v": 1,
  "point": "unit1.zone_air_temp",
  "value": 21.52,
  "unit": "DEG_C",
  "sensor_time": "2026-10-14T12:00:00Z",
  "ingest_time": "2026-10-14T12:00:00.400Z",
  "quality": "GOOD"
}
```

- **`v`**: the schema version, fixed at `1` for now. If the shape ever changes, it becomes `2`, and old stored messages can still be read correctly.
- **`point`**: the standard point ID. It must match a `ref:hasTimeseriesId` in `../dtteo_asset_model.ttl`, which is the link between telemetry and meaning. The pattern forces `something.something` in lowercase, so raw device names like `t1` are rejected (see `invalid/raw_device_name.json`).
- **`value`**: a number, string or boolean (see decision 2 below).
- **`unit`**: a QUDT unit ID (see decision 1 below).
- **`sensor_time`**: when it was *measured*.
- **`ingest_time`**: when *we received* it. Both times must be UTC and end in `Z` (see decision 3 below).
- **`quality`**: one of `GOOD`, `SUSPECT` or `BAD`, set by the validator.
- **`source`**: *optional*. Which adapter and device the reading came from, e.g. `mqtt-acme:ACME-HVAC-0001`, for tracing problems.

### Decisions (and the alternatives I didn't take)

**1. Units use QUDT IDs (`DEG_C`, `KiloW`, `PERCENT`), not `degC` or `°C`.**
- *Why:* the asset model already uses QUDT (`brick:hasUnit unit:DEG_C`), so the message and the model use exactly the same name. No translation table is needed between them.
- *Alternative:* SenML/UCUM symbols (`Cel`, `kW`, `%`), which are shorter but would need mapping to the asset model.
- *Knock-on:* the README and D-04 diagram currently show `degC`. They need a small update to `DEG_C`.

**2. `value` can be a number, string or boolean.**
- *Why:* the asset model has a mode point (`unit1.mode_cmd`) whose value is `heat`, `cool` or `off`. Forcing it to a number code (1, 2, 3) would hide its meaning.
- *Trade-off:* the storage layer has to handle mixed types. Most readings will be numbers, so this is a small cost.

**3. Times must be UTC, with a `Z` on the end.**
- *Why:* one time zone everywhere avoids daylight-saving bugs (the UK changes clocks twice a year). Local times like `+01:00` are rejected (see `invalid/local_time_not_utc.json`). Converting to UTC is the normaliser's job.

**4. `additionalProperties: false`: unknown fields are rejected.**
- *Why:* it catches typos. `"vaule"` instead of `"value"` fails straight away (see `invalid/typo_in_field.json`) instead of silently storing nothing.
- *Trade-off:* adding a new field later means updating the schema. That's intended: changes to the contract should be deliberate.

**5. One message carries one reading.**
- *Why:* it's simpler to route, store and check. A device that sends temperature and humidity together gets split into two messages by the adapter.
- *Alternative:* batches (SenML supports lists of readings). These could be added later if message volume becomes a problem; at v0.1 scale it isn't.

**6. `source` is optional for now.**
- *Why:* it's useful for debugging, but CSV imports and the simulated plant don't always have a meaningful device ID. It can become required once all adapters set it.

### Something I noticed in the existing code

In the root prototype, `testing/adapter/vendor_acme_publisher.py` and `vendor_borealis_publisher.py` each define their vendor format (`to_acme_payload`, `to_borealis_payload`), but **neither function is ever called**. Both scripts publish the same generic payload as `mqtt-pipeline/publisher.py`.

So right now the two "vendors" send identical data, and they can't yet test the adapter idea. At the start of step 2 they'll be copied into `v0.1/testing/vendors/` and fixed there, so they really send different formats:
- **acme:** Fahrenheit, epoch milliseconds, mode as a number;
- **borealis:** a list of readings, Celsius, mode in capitals.

(Also, in the root `docker-compose.yml`, the `borealis-publisher` service has its `build:` line commented out, so it won't start.)

### Open questions

- Should `quality` carry a reason, e.g. `"quality_reason": "above range"`? For now the reason goes to logs and the quarantine topic. Worth adding if dashboards need to show it.
- Should `point` IDs include the site, e.g. `site1.unit1.zone_air_temp`? Not needed with one site. Revisit before adding a second site.

### Next: step 1b, topic names

Decide the MQTT topic structure: where raw device data arrives, where canonical messages go, and the quarantine topic. This will be written up as `topics.md` in this folder.

---

## 2026-10-14 · Moved into v0.1

This folder was first created at the repo root by mistake. It now lives at `v0.1/contracts/`, so the design docs and the build sit together and the earlier prototype in the root stays as it was. Paths in these notes were updated to match. Nothing in the schema or examples changed.

---

## 2026-10-14 · Step 1b: topic names

### What I added

`topics.md`: the full topic map, naming rules, QoS/retain choices, online/offline status, and a draft of the broker access rules.

### Decisions (and the alternatives I didn't take)

**1. Two separate zones: `raw/...` and `dt/v1/...`.**
- Devices write native data to `raw/{source}/{device}/...`. Only the ingestion gateway reads it, and only the gateway writes canonical messages to `dt/v1/telemetry/...`.
- *Why:* it makes the "front door" rule visible in the topic names, and later enforceable with broker access rules.
- *Alternative:* devices publish straight to canonical topics. That's simpler, but any device could then send badly formed "canonical" data.

**2. Message class comes before site and equipment (`dt/v1/telemetry/site1/...`, not `dt/v1/site1/unit1/telemetry`).**
- *Why:* most services want one *class* of message (all telemetry, all alerts). Class-first means one wildcard covers it, e.g. `dt/v1/telemetry/#`.
- *Alternative:* the Unified Namespace / ISA-95 style puts the site hierarchy first. It's better when people browse topics by location; worth revisiting if a UNS is ever needed at pilot.

**3. The canonical topic is derived from the point ID (`.` becomes `/`).**
- *Why:* there's one source of truth for names (the asset model) and no separate lookup table for topics.

**4. `v1` is in the topic as well as in the message.**
- *Why:* the message's `v` says which *schema* a message uses. The topic's `v1` lets a future topic layout run alongside this one during a switch-over. They usually change together, but don't have to.

**5. QoS 1 for canonical data, with nothing retained except status and twin state.**
- *Why:* a dropped reading matters more than a rare duplicate, and duplicates can be ignored at storage time (same `point` + `sensor_time`). Retaining readings would hand new subscribers an old value as if it were current.

### Knock-on changes to make

- **D-07 (what-if diagram) and the README** use `dt/scn/req` and `dt/scn/res/r42`. These should become `dt/v1/scenario/req` and `dt/v1/scenario/res/r42`. They'll be updated together with the `degC` → `DEG_C` change from step 1a.
- The root prototype publishes to `asset/hvac_01/telemetry` and `vendor/.../...`. The fixed copies in `v0.1/testing/vendors/` will publish to `raw/acme/...` and `raw/borealis/...`.

### Still open

- **The quarantine message needs its own small schema.** It should carry at least the original topic, the raw payload, the reason and when it was received. That will be written in step 2, alongside the gateway that produces it.
- Should **commands** (later phase) get their own class, e.g. `dt/v1/cmd/...`? Yes, most likely, but it stays out of v0.1 until the command path is designed.

### Next: step 2, ingestion gateway v0

1. Copy the acme and borealis publishers into `v0.1/testing/vendors/` and fix them so they really send different formats, on `raw/...` topics.
2. Build the first gateway pieces: the MQTT adapter and the mapper (reading the asset model).

---

## 2026-10-28 · Step 2i: canonical message v2 (site, time source, qc reasons)

Before anything is stored (stage 3), three gaps in v1 were closed. Changing the shape now costs a few tests; changing it after data is stored means migrating that data. `v` goes from `1` to `2` because a v2 message isn't valid v1 and vice versa (decision 1 in step 1a said exactly this).

### What changed

```json
{
  "v": 2,
  "site": "site1",
  "point": "unit1.power",
  "value": 12.4,
  "unit": "KiloW",
  "sensor_time": "2026-10-14T12:00:05Z",
  "ingest_time": "2026-10-14T12:00:05.120Z",
  "time_source": "device",
  "quality": "SUSPECT",
  "qc": [{"test": "expected_range", "flag": "SUSPECT", "reason": "12.4 is outside the expected range 0.0..10.0"}]
}
```

| Field | New? | Why |
|---|---|---|
| `site` | required | Point IDs are only unique **within** a site. Two sites would both have `unit1.zone_air_temp`, and storage that skips duplicates by point + time would silently drop the second site's readings. SenML has the same rule: base name + name "must result in a globally unique identifier" ([RFC 8428 §4.2](https://www.rfc-editor.org/rfc/rfc8428)). The site was already in the topic; it is now in the message too, so storage never has to parse topics. |
| `time_source` | required | `"device"` or `"gateway"`. If a device sends no time, the gateway uses the arrival time (SenML treats a missing time as "roughly now", [RFC 8428 §4.5.3](https://www.rfc-editor.org/rfc/rfc8428)). That time is less precise, **and** an MQTT QoS 1 re-delivery of such a message gets a *new* time, so storage can't recognise it as a duplicate. Marking it means analysis knows which times to trust. |
| `qc` | optional | Only when quality isn't GOOD: one entry per check that flagged it (`sensor_range`, `expected_range`, `future_time`, `late_arrival`). Before, the reasons only reached the gateway log, so a stored BAD reading couldn't say why. QARTOD tools keep a flag per test for the same reason ([ioos_qc](https://github.com/ioos/ioos_qc)). This closes the open question from steps 1a and 2g. |

The quarantine message is also v2: it gains `site`, and a new stage `internal` (step 2j).

### Examples

- `examples/valid/*` moved to v2; `power_suspect.json` now shows a `qc` list.
- New invalid examples: `missing_site.json`, `old_version_1.json` (a v1 message is rejected), `empty_qc.json` (`qc` must list at least one check, or be left out).

### Decisions

**1. Site goes in the message, not in the point ID.** *Alternative:* rename points to `site1.unit1.zone_air_temp`. That would make the asset model site-specific in every ID and break the "topic = site + point" rule in `topics.md`. Keeping site separate matches how the topic is already built.

**2. Devices should send their own time.** `time_source: "gateway"` is allowed, not an error, because some sources (a simple sensor, the CSV importer without a time column) genuinely have no clock. But for devices we control, set the time on the device: Tasmota and ESPHome both sync over NTP and include the time in their messages.

**3. No `qc` on GOOD readings.** Keeps the common message small; "no qc" means "nothing flagged".

### Still open

- The open question from step 1a, "should `point` IDs include the site?", is answered: no, `site` is its own field.
