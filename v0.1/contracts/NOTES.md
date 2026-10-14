# contracts/: developer notes

Working notes for the message contract. Everything for this build lives in `v0.1/`; the root folders (`mqtt-pipeline`, `storage`, `testing`) are the earlier prototype and are left untouched. Each entry records what changed, why, and what's still open. Newest entry at the bottom.

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
