# services/ingestion-gateway/: developer notes

The gateway is the system's front door: raw device data comes in, canonical messages go out (see `../../contracts/`). It is being built one piece at a time, in the order of the D-03 diagram. Newest entry at the bottom.

```
transport (MQTT, file, ...) → DECODER → MAPPER → normaliser → validator → publisher
                                  2c       2b
```

---

## 2026-10-14 · Step 2b: mapper

### The job

The mapper answers one question: **"this vendor's field, from this device, is which of our points?"**

```
("acme",     "acme_hvac_0001", "tempF")        →  unit1.zone_air_temp   (DEG_C, vendor sends DEG_F)
("borealis", "site4_hvac_01",  "temperature")  →  unit1.zone_air_temp   (DEG_C)
("acme",     "acme_hvac_0001", "rh")           →  None  → quarantine
```

It doesn't convert values, check ranges or publish anything. Those jobs belong to the next pieces.

### What I added or changed

| File | What |
|---|---|
| `gateway/mapper.py` | The mapper: loads the files once, then answers lookups from a dictionary |
| `tests/test_mapper.py` | 8 tests against the real model and mapping files |
| `requirements.txt` | `rdflib` (reads Turtle and runs queries), `pytest` (tests) |
| `../../mappings/dtteo_ref.ttl` | **New:** our one extension to Brick: the `RawFieldReference` type |
| `../../mappings/acme.ttl`, `borealis.ttl` | **New:** one mapping file per vendor |
| `../../dtteo_asset_model.ttl` | **Changed:** added the `unit1.mode_status` point |

### Where the mappings live, and why

I had two options:

- **A. A separate config file per adapter**, e.g. YAML: `tempF: unit1.zone_air_temp`. This is simple, but it's a second list of point names that can drift away from the asset model.
- **B. The semantic model itself.**  Chosen.

Brick already has a pattern for "how does an outside system refer to this point?", called **external references**. A point can carry several, one per system:

```turtle
:zone_temp ref:hasExternalReference [ a ref:TimeseriesReference ; ref:hasTimeseriesId "unit1.zone_air_temp" ] .  # database
:zone_temp ref:hasExternalReference [ a ref:BACnetReference ; ... ] .                                          # BACnet (built into Brick)
:zone_temp ref:hasExternalReference [ a dtteo:RawFieldReference ;                                              # ours
                                      dtteo:source "acme" ; dtteo:device "acme_hvac_0001" ; dtteo:field "tempF" ] .
```

Brick ships reference types for BACnet, IFC (building models) and time-series databases. I added one more, `dtteo:RawFieldReference`, in `mappings/dtteo_ref.ttl`, written the same way Brick writes its own. When I first loaded it, Brick's validator insisted that every reference type has a `skos:definition`, so it has one.

**Why this matters:** the asset model now *does real work*. The gateway literally runs a query against it to route data. The 2026 review flagged that most twins declare semantics but never use them; this is the opposite.

**Why one mapping file per vendor:** adding a vendor means adding **one adapter + one mapping file**. Removing a vendor means deleting them. The asset model itself doesn't change.

### How it works (in `mapper.py`)

1. Load the asset model and every mapping file into one graph. RDF graphs merge naturally, because files that mention the same node (e.g. `:zone_temp`) are describing the same thing.
2. Run **one SPARQL query** that joins each raw field reference → its point → that point's time-series ID and unit.
3. Store the results in a plain Python dictionary keyed by `(source, device, field)`.
4. From then on, `lookup()` is just a dictionary read. The graph is **never queried per message**, so this stays fast however busy the broker gets.

SPARQL, in one sentence: it's the query language for RDF graphs. You write a pattern of arrows with blanks (`?point ref:hasExternalReference ?raw`), and it returns every way the blanks can be filled in.

### Safety checks at start-up

The mapper refuses to start (`MappingError`) if:
- **a vendor field is mapped to two different points**, which would be ambiguous. There's a test that creates this clash on purpose;
- **a mapped point has no time-series ID**, so its data could never be stored.

It's better to fail loudly at start-up than to mis-route data quietly for weeks.

### Decisions

**1. Device = the slug from the topic** (`acme_hvac_0001`), not the vendor's own ID inside the payload (`ACME-HVAC-0001`).
- *Why:* the topic is always there and already cleaned up. Payload formats differ per vendor.

**2. Nested fields are written with a dot**, e.g. `status.mode` for Borealis's `{"status": {"mode": ...}}`.
- *Why:* it's readable, and the adapter will produce field names in the same form.

**3. `unit1.mode_status` was added to the asset model** (Brick class `Mode_Status`). `mode_cmd` is now labelled "Requested operating mode".
- *Why:* devices *report* the mode they're in. That's a status, not a command. Mixing the two would confuse the twin and, later, the command path.

**4. Enum values (`2` → `cool`, `HEATING` → `heat`) are *not* the mapper's job.**
- *Why:* the mapper only names things. Translating values belongs to the normaliser (next step), which keeps each piece small.

**5. Only `rdflib` at runtime, not the full `brickschema` package.**
- *Why:* `rdflib` is much lighter. Full Brick validation is still run separately whenever the model changes (the command is in `../../README.md`).

### Try it (Windows, from a terminal)

```bat
cd v0.1\services\ingestion-gateway
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt

python -m pytest              :: 8 passed
python -m gateway.mapper      :: list every mapping
```

- `venv` is a **virtual environment**: a private copy of Python just for this service, so its libraries don't clash with other projects. You'll see `(venv)` at the start of the terminal line when it's active. Run `venv\Scripts\activate` again in each new terminal.
- In **VS Code**, red underlines on `import rdflib` or `import pytest` mean the editor is using a different Python. Press `Ctrl+Shift+P`, choose **Python: Select Interpreter**, and pick the one inside `services\ingestion-gateway\venv`.

Output of the listing:

```
source     device           field          -> point                  unit (raw)
acme       acme_hvac_0001   op_state       -> unit1.mode_status      -
acme       acme_hvac_0001   tempF          -> unit1.zone_air_temp    DEG_C (raw DEG_F)
borealis   site4_hvac_01    status.mode    -> unit1.mode_status      -
borealis   site4_hvac_01    temperature    -> unit1.zone_air_temp    DEG_C
```

### Knock-on changes (batched with the earlier ones)

- The D-05 diagram and the README asset-model section should show `mode_status`.
- The README section on the mapper can now point at real files.

### Next: step 2c, adapters (decode)

Write the Acme and Borealis **decoders**: each turns its vendor's message into a list of plain raw records `(field, value, time)` that the mapper can look up. This is where the Normalizer pattern's "one translator per format" lives.

---

## 2026-10-15 · Fix: tests didn't run on Windows

The tests themselves were fine, but running them depended on *where* you ran them from, and the listing command relied on `*.ttl`, which Windows terminals don't expand.

- Added **`pytest.ini`**. It tells pytest where the tests are and lets them import `gateway`. `python -m pytest` now works from this folder, from `v0.1`, or from anywhere (all three checked).
- **`python -m gateway.mapper`** now needs no arguments. It finds the asset model and the `mappings` folder itself, and searches for `.ttl` files in Python, so it behaves the same on every system.
- Added **`v0.1/.gitignore`** so virtual environments and cache folders aren't committed.
- Rewrote "Try it" above with Windows commands and the VS Code interpreter fix.

---

## 2026-10-15 · Step 2c: decoders

### Transport and format are two different jobs

The D-03 diagram has one box per "protocol adapter", but that box does two separate things:

| Job | Question it answers | Examples | Built in |
|---|---|---|---|
| **Transport** | *How* do the bytes arrive? | subscribe over MQTT, read a CSV file, poll Modbus | a later step (wiring the service) |
| **Format** | *What* do the bytes mean? | Acme's flat object, Borealis's list of readings | **this step (decoders)** |

They're independent: Acme could send the same format over MQTT today and in a CSV export tomorrow. Keeping them apart means a new vendor never needs new connection code, and a new connection type never needs new vendor code.

### What I added

| File | What |
|---|---|
| `gateway/decoders/__init__.py` | `RawRecord`, `DecodeError`, topic parsing, and the registry that picks a decoder from the topic |
| `gateway/decoders/acme.py` | Acme decoder |
| `gateway/decoders/borealis.py` | Borealis decoder |
| `gateway/demo.py` | `python -m gateway.demo` prints decode + map for the sample messages |
| `tests/samples/*.json` | One real message from each vendor, captured from the scripts in `testing/vendors/` |
| `tests/test_decoders.py` | 16 tests, including decode + map together |

### What a decoder produces

Every decoder turns its vendor's message into a list of the same simple thing, a **RawRecord**:

```python
RawRecord(source="acme", device="acme_hvac_0001", field="tempF", value=70.4, time=<19:33:38 UTC>)
```

The mapper then only ever sees RawRecords, whatever vendor they came from. In the *Normalizer* pattern from Enterprise Integration Patterns, the decoders are the "one translator per format" boxes.

### Rules every decoder follows (and why)

1. **Understand syntax only.** A decoder knows where the values *are* in the message and how to read its time format, nothing more.
2. **Don't convert anything.** `70.4` stays Fahrenheit and `2` stays Acme's code. Conversion is the normaliser's job (next step), done once for every vendor, driven by the mapping files (`rawUnit`). If each decoder did its own conversion, the same F→C maths would be copied into every vendor.
3. **Emit every field and filter nothing.** If Acme adds a new field next year, it reaches the mapper, isn't found, and lands in quarantine where someone can see it. If decoders only picked out the fields they "knew", new data would silently vanish.
4. **If the whole message can't be read, raise `DecodeError`.** Examples: not JSON, a time with no timezone, an unknown vendor. The gateway will quarantine the whole message, with the reason.

### Time handling

- **Acme:** `ts` is milliseconds since 1970 in UTC. The decoder turns it into a proper time (`19:33:38.428 UTC`).
- **Borealis:** each reading has an ISO time with its offset (`20:33:38+01:00`). The decoder keeps the offset; converting to UTC is the normaliser's job.
- A Borealis time **without** an offset is rejected. `20:33:38` alone is ambiguous: UK time or UTC? Guessing would silently shift data by an hour for half the year.
- Borealis's `status` block has no time of its own, so it uses the newest reading time in the same message.
- The test `test_both_samples_are_the_same_instant` checks that Acme's `1792006418428` ms and Borealis's `20:33:38+01:00` are the same moment, so neither decoder is an hour out.

### Decisions

**1. The device comes from the topic, not the payload.** This matches the mapper (step 2b).

**2. Nested fields are flattened with a dot** (`status.mode`). This matches how the mapping files name them.

**3. Borealis's own `"unit": "C"` label is currently ignored.** The mapping file is the authority on units. *Possible later check:* if a vendor's declared unit disagrees with the mapping, mark the reading SUSPECT.

**4. Decoders are looked up by the `source` level of the topic** (`raw/acme/...` → Acme decoder). Adding a vendor means one decoder module, one line in `DECODERS`, and one `mappings/<vendor>.ttl`.

### Try it

```bat
cd v0.1\services\ingestion-gateway
venv\Scripts\activate
python -m pytest              :: 24 passed
python -m gateway.demo        :: see both vendors decoded and mapped
```

Demo output:

```
raw/acme/acme_hvac_0001/telemetry
  tempF        = 70.4      @ 2026-10-14T19:33:38.428000+00:00  -> unit1.zone_air_temp
  rh           = 54.0      @ 2026-10-14T19:33:38.428000+00:00  -> QUARANTINE (unknown point)
  op_state     = 2         @ 2026-10-14T19:33:38.428000+00:00  -> unit1.mode_status

raw/borealis/site4_hvac_01/data
  temperature  = 21.29     @ 2026-10-14T20:33:38+01:00         -> unit1.zone_air_temp
  humidity     = 55.6      @ 2026-10-14T20:33:38+01:00         -> QUARANTINE (unknown point)
  status.mode  = COOLING   @ 2026-10-14T20:33:38+01:00         -> unit1.mode_status
```

Both vendors now reach the **same points**. The values and times are still in each vendor's own form (°F vs °C, `2` vs `COOLING`, UTC vs +01:00).

### Next: step 2d, normaliser

Make the values identical as well:
- °F → °C, using `dtteo:rawUnit` from the mapping files;
- every time → UTC ending in `Z`;
- vendor mode words and codes (`2`, `COOLING`) → `heat` / `cool` / `off`. These value maps will go in the mapping files, so vendor knowledge stays in data, not code.
