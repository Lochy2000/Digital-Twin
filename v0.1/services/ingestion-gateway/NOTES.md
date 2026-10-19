# services/ingestion-gateway/: developer notes

The gateway is the system's front door: raw device data comes in, canonical messages go out (see `../../contracts/`). It is being built one piece at a time, in the order of the D-03 diagram. Newest entry at the bottom.

```
transport (MQTT, file, ...) → DECODER → MAPPER → NORMALISER → validator → publisher
                                  2c       2b        2d
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

---

## 2026-10-15 · Step 2d: normaliser

### The job

The decoders and mapper got both vendors onto the **same points**. The normaliser makes the **values** the same too:

```
                         before (vendor's own)              after (standard)
Acme      tempF       =  70.4      @ 19:33:38.428 UTC   ->  21.3333 DEG_C @ 2026-10-14T19:33:38.428Z
Borealis  temperature =  21.29     @ 20:33:38+01:00     ->  21.29   DEG_C @ 2026-10-14T19:33:38.000Z
Acme      op_state    =  2                              ->  cool
Borealis  status.mode =  COOLING                        ->  cool
```

Its output is the canonical message **minus `quality`**. Quality is added by the validator (next step).

### What I added or changed

| File | What |
|---|---|
| `gateway/normaliser.py` | **New.** The five normalising steps (below) |
| `gateway/units.py` | **New.** Unit conversion using QUDT's multiplier and offset rule |
| `gateway/mapper.py` | **Changed.** Also loads value maps from the mapping files |
| `../../mappings/dtteo_ref.ttl` | **Changed.** Adds `dtteo:valueMap` (with `from` and `to`) |
| `../../mappings/acme.ttl`, `borealis.ttl` | **Changed.** Value maps for each vendor's mode |
| `tests/test_normaliser.py`, `tests/test_units.py` | **New.** 22 tests, including a contract check |
| `requirements.txt` | **Changed.** Adds `jsonschema` for the contract check |

### The five steps, always in this order

1. **Value map:** a vendor word or code becomes ours (`2` becomes `cool`).
2. **Scale:** multiply first if the device sends scaled numbers (`2152` × 0.01 = `21.52`).
3. **Unit:** convert the vendor's unit to the point's unit (DEG_F to DEG_C).
4. **Tidy:** round to 4 decimal places to remove floating-point noise. `21.333333333333336` becomes `21.3333`. This isn't a judgement about how precise the sensor is; that's for the validator or the asset model later.
5. **Times:** both times become UTC text ending in `Z`, with milliseconds. If the device gave no time, the ingest time is used (as the contract says).

The order matters. Scaling must happen before converting (`2152` isn't a temperature yet), and the value map comes first because a mode isn't a number at all.

### Where the vendor knowledge lives: value maps in the mapping files

```turtle
:mode_status ref:hasExternalReference [
    a dtteo:RawFieldReference ;
    dtteo:source "acme" ; dtteo:device "acme_hvac_0001" ; dtteo:field "op_state" ;
    dtteo:valueMap [ dtteo:from "1" ; dtteo:to "heat" ] ,
                   [ dtteo:from "2" ; dtteo:to "cool" ] ,
                   [ dtteo:from "3" ; dtteo:to "off"  ]
] .
```

- *Why here and not in the decoder:* "Acme's 2 means cool" is a fact about Acme, the same kind of fact as "Acme's tempF is the zone temperature". Keeping all of it in the mapping file means **one place per vendor** for vendor knowledge, and the normaliser code never mentions a vendor.
- **Borealis has no `off`** in its map, because its script never sends one. If it ever does, `OFF` isn't in the map, so the reading is **quarantined** with the reason "value 'OFF' is not in the value map". Someone then adds one line. That's the intended behaviour: never guess.
- Brick validation still passes with these added.

### Unit conversion: following QUDT, not a hand-written formula

The asset model uses QUDT units, and QUDT publishes how to convert every unit. Each unit has a **multiplier** and an **offset** to its SI base unit (kelvin for temperature):

```
value_in_SI   = (value + offset) × multiplier
value_in_unit = value_in_SI ÷ multiplier − offset
```

| Unit | Multiplier | Offset | Source |
|---|---|---|---|
| DEG_F | 0.5555… (5/9) | 459.67 | [qudt.org/vocab/unit/DEG_F](https://qudt.org/vocab/unit/DEG_F) |
| DEG_C | 1.0 | 273.15 | [qudt.org/vocab/unit/DEG_C](https://qudt.org/vocab/unit/DEG_C) |

So °F to °C is computed as °F to K to °C. The same two lines of code handle **any** pair of units of the same kind: W to kW, % to fraction, and so on. `units.py` only lists the units v0.1 uses; adding one means copying its two numbers from the QUDT page. Converting between different kinds (kW to °C) is refused.

The calculation uses Python's `Decimal` type, so `32 °F` comes out as exactly `0 °C` rather than `-0.0000000001`.

### What goes to quarantine from this step

`NormaliseError` is raised, with a plain reason, when:
- a word or code isn't in the value map;
- text, `None` or `true`/`false` arrives where a number is expected;
- units can't be converted (unknown unit, or a different kind of quantity).

### The contract check

`test_output_is_a_valid_canonical_message` takes every normalised reading from both vendors, adds `quality: GOOD`, and checks it against `contracts/canonical_message.schema.json`. If the normaliser ever drifts from the contract agreed in step 1, this test fails straight away.

### Decisions

**1. The normaliser doesn't judge values.** 999 °C passes through normalisation unchanged; deciding it's wrong (SUSPECT or BAD) is the validator's job. That keeps each piece doing one thing.

**2. `source` is set to `<vendor>:<device>`**, e.g. `acme:acme_hvac_0001`, so any reading can be traced back to where it came from.

**3. Booleans are not numbers here.** In Python `True == 1`, so a device sending `true` for a temperature would otherwise become `1.0 °C`. It's refused explicitly.

### Try it

```bat
cd v0.1\services\ingestion-gateway
venv\Scripts\activate
pip install -r requirements.txt     :: jsonschema is new
python -m pytest                    :: 48 passed
python -m gateway.demo
```

```
raw/acme/acme_hvac_0001/telemetry
  tempF = 70.4           -> unit1.zone_air_temp  = 21.3333 DEG_C  @ 2026-10-14T19:33:38.428Z
  rh = 54.0              -> QUARANTINE: unknown point
  op_state = 2           -> unit1.mode_status    = cool  @ 2026-10-14T19:33:38.428Z

raw/borealis/site4_hvac_01/data
  temperature = 21.29    -> unit1.zone_air_temp  = 21.29 DEG_C  @ 2026-10-14T19:33:38.000Z
  humidity = 55.6        -> QUARANTINE: unknown point
  status.mode = COOLING  -> unit1.mode_status    = cool  @ 2026-10-14T19:33:38.000Z
```

The two temperatures differ slightly only because each fake vendor adds its own random noise; the format is now identical.

### Next: step 2e, validator

Decide each reading's `quality` (GOOD / SUSPECT / BAD) with simple, explainable checks:
- is the value in a plausible range for this kind of point?
- is the time sensible (not in the future, not years old)?
- is it a duplicate?

The plausible ranges will be stored with the points, not hard-coded.

> **Changed plan (2026-10-16):** the validator moves to step 2g. Step 2e became device types and bindings (below), and step 2f will add decoders for the two real formats.

---

## 2026-10-16 · Step 2e: device types and bindings

### The job

Until now, every mapping was written **per device**. Twenty identical units would mean the same vendor knowledge copied twenty times. The design for fixing this is in `mappings/DESIGN.md`; this step builds it. Everything downstream of the mapper (decoders, normaliser, contract) is unchanged.

### Two real formats added, so the design isn't shaped by the fake vendors

Acme and Borealis are made up (`testing/vendors/`). They stay as test cases, but the design now also has to hold for two **real, published** formats:

| | What it is | Why it's a good test |
|---|---|---|
| **Tasmota + DS18B20** | Open-source firmware for the ESP8266 (the board on hand), with a common temperature probe. Publishes JSON over MQTT. | Sends **local time with no offset**; the unit (C or F) is a setting, stated in the message; the probe is **generic**, so what it measures depends on where it's installed. |
| **Eastron SDM120** | A widely sold single-phase electricity meter, often fitted to meter a heat pump. Read over **Modbus** (polled, not pushed). | Values are **registers**, not named fields; each is a 32-bit float across 2 registers; sends watts, our point is kW. |

Sources: Tasmota DS18x20 docs (example message), and for the SDM120 two independent register lists (aggsoft's table and the `sdm-modbus` Python library, whose code reads all of them as input registers, float32, big-endian byte and word order). Still to check against Eastron's own PDF before a real meter is used.

### What I added or changed

| File | Purpose |
|---|---|
| `mappings/dtteo_onboarding.ttl` | Vocabulary: `DeviceType`, `DeviceBinding` and their properties, each commented |
| `mappings/types/*.ttl` | One file per device model: `acme_hvac`, `borealis_hvac`, `tasmota_ds18b20`, `eastron_sdm120` |
| `mappings/bindings/site1.ttl` | The installed devices: one short block each |
| `mappings/acme.ttl`, `borealis.ttl` | Emptied (content moved into types + bindings). **Safe to delete.** |
| `gateway/mapper.py` | Builds its table from types + bindings; start-up rules; `binding()` lookup; check output |
| `tests/test_mapper.py` | Rewritten: real formats, the rules, the swap |
| `tests/test_normaliser.py`, `test_decoders.py`, `gateway/demo.py` | One mapper per fake vendor (see "one source per point") |

### How a field finds its point now

```
message from acme_hvac_0001, field "tempF"
  binding  acme_hvac_0001  -> type acme_hvac, serves unit1
  type     tempF           -> a brick:Zone_Air_Temperature_Sensor, raw unit DEG_F
  model    unit1 -feeds-> zone1 -hasPoint-> zone_temp (that class)  -> "unit1.zone_air_temp"
```

The type names the **Brick class** of point, not a point ID. The mapper then finds the point of that class on the equipment the device serves (or on what that equipment feeds). This is how Brick applications are meant to find points: by what they are, not by their names.

Two exceptions, both handled in the **binding**:
- **Generic sensors** (the Tasmota probe): the type only knows "a temperature". The binding **places** it: `dtteo:place [ field "DS18B20.Temperature" ; point :zone_temp ]`.
- **Two points of the same class** on one piece of equipment: start-up stops and asks for a `dtteo:place`.

Modbus values have no field name, so the mapper builds one from the W3C terms: `modv:entity "InputRegister"` + `modv:address 12` gives the field `InputRegister:12`.

### The start-up rules

| Rule | Example of what it catches |
|---|---|
| 1. A binding names exactly one existing type, and equipment that exists | a typo in a type name |
| 2. Every **required** value finds a point; **optional** ones are reported | forgot to add a point to the asset model |
| 3. Only one enabled source per point | Acme and Borealis both feeding the zone temperature |
| (kept) A field can't map to two points | two mappings claiming the same field |

### One source per point, and the on/off switch

Acme, Borealis and the Tasmota probe would all feed `unit1.zone_air_temp`, so rule 3 allows only one of them at a time. Each binding has `dtteo:enabled` (default on). Disabled bindings are still checked at start-up, but their data goes to quarantine. In `site1.ttl`, Acme is on; Borealis and Tasmota are off. Tests and the demo swap using an override (`Mapper.from_folder(v01, enabled={...})`) instead of editing the file.

### Decisions

**1. Brick class matching is exact.** A type saying `Temperature_Sensor` won't match a `Zone_Air_Temperature_Sensor` point. Subclass matching needs the whole Brick ontology loaded at start-up (slow, and not needed yet). Generic sensors are placed instead.

**2. The "check" command is the mapper's own command line.** `python -m gateway.mapper` prints every mapping plus notes; if anything is wrong it stops with a message saying what to fix. DESIGN.md had proposed a separate `gateway.check`; one command is simpler.

**3. Instance details are stored now, used later.** Tasmota's timezone and the SDM120's Modbus address are in the bindings and readable through `mapper.binding(...)`, but nothing uses them until the Tasmota decoder (2f) and a Modbus poller.

**4. The optional SDM120 values have units the converter doesn't know yet** (V, A, Hz, kWh). They're not mapped, so it doesn't matter now. Add them to `units.py` when points for them are added.

### Checked

- 58 tests pass.
- Brick validation: the new files add no violations. (The only ones reported are the 7 unit checks on existing points, because this `brickschema` install doesn't load QUDT's unit list; same result for the asset model on its own.)

### Try it

```bat
cd v0.1\services\ingestion-gateway
venv\Scripts\activate
python -m pytest              :: 58 passed
python -m gateway.mapper      :: the check: every mapping + notes
python -m gateway.demo        :: unchanged output
```

```
source    device          field                -> point                  unit (raw)
acme      acme_hvac_0001  op_state             -> unit1.mode_status      -
acme      acme_hvac_0001  tempF                -> unit1.zone_air_temp    DEG_C (raw DEG_F)
modbus    sdm120_unit1    InputRegister:12     -> unit1.power            KiloW (raw W)

Notes:
  - binding acme_hvac_0001, field 'rh': optional, unit1 has no brick:Zone_Air_Humidity_Sensor point, so not mapped
  - binding sdm120_unit1, field 'InputRegister:0': optional, unit1 has no brick:Voltage_Sensor point, so not mapped
  ...
  - borealis/site4_hvac_01: binding disabled, its data will be quarantined
  - tasmota/tasmota_zone1: binding disabled, its data will be quarantined
```

Try breaking it: in `bindings/site1.ttl`, change Borealis to `dtteo:enabled true` and run the check. It stops, naming the point that now has two sources.

### Next: step 2f, decoders for the real formats

- **Tasmota:** flatten the JSON (`DS18B20.Temperature`), check `TempUnit`, and turn local time into UTC using the binding's timezone.
- **Modbus:** turn raw register values into numbers using `modv:type` and the byte/word order (a float across 2 registers). Polling a real meter comes later; this step decodes register values given to it, with a simulated SDM120 for tests.

---

## 2026-10-18 · Step 2f: decoders for the two real formats, and source links in the code

### Source links in every code file

Each code and model file now ends its header with a **Sources** list: the spec, docs page or library each rule in that file follows. Where a single rule comes from somewhere specific, the link is also next to that line (e.g. rule 3 in `mapper.py` -> AWS SiteWise).

To see it all in one place: `v0.1/SOURCES.md` lists every link and which files cite it. It is generated, so it can't go stale:

```bat
cd v0.1
python tools\list_sources.py
```

Every link was opened and checked while writing this step. The QUDT unit values were re-checked on qudt.org.

### Tasmota decoder (`gateway/decoders/tasmota.py`)

| Tasmota sends | Decoder does |
|---|---|
| Nested JSON: `{"DS18B20": {"Temperature": 21.4}}` | Flattens with dots: `DS18B20.Temperature` |
| `Time`, `TempUnit`, the probe's `Id` | Treats as metadata, not readings |
| `"TempUnit": "C"` or `"F"` | Passes it on as the record's unit (`DEG_C` / `DEG_F`); the normaliser converts F to C |
| Local time, no offset: `"2026-10-18T11:22:00"` | Uses the binding's timezone (`Europe/London`) -> `10:22:00Z` |
| Time with an offset (if `SetOption52` is on) | Uses it as given; no timezone needed |
| `tele/LWT` = `Online` / `Offline` (plain text) | One record, field `LWT` (unmapped, so quarantined for now) |

**Topic setup.** Tasmota normally publishes on `tele/<topic>/SENSOR`. Two Tasmota commands put it on our raw topic instead: `Topic tasmota_zone1` and `FullTopic raw/tasmota/%topic%/%prefix%/`. No firmware change. Recorded in `contracts/topics.md`.

**The hour that happens twice.** When UK clocks go back (25 Oct 2026, 02:00 -> 01:00), local times from 01:00 to 01:59 happen twice. Without an offset, `01:30` could mean two different moments. The decoder refuses these (quarantine) rather than guess. Turning on `SetOption52` on the device avoids the problem entirely, so that's the recommended setting.

### Modbus decoder (`gateway/decoders/modbus.py`)

Modbus devices don't send anything: something has to ask. A **poller** (a later step) will read the registers listed in the device type and publish exactly what came back:

```json
{"time": "2026-10-18T10:22:00.000Z",
 "registers": {"InputRegister:12": [17551, 53248]}}
```

The decoder turns `[17551, 53248]` into `1150.5` using the type's `modv:type` (`xsd:float` = 2 registers) and byte/word order. Then the normaliser turns 1150.5 W into 1.1505 kW as before.

Why split it like this: the poller stays simple (it just copies registers), the raw topic shows exactly what the meter said, and the tricky part (byte order) is tested without any hardware.

### What I added or changed

| File | Change |
|---|---|
| `gateway/decoders/tasmota.py`, `modbus.py` | New |
| `gateway/decoders/__init__.py` | Registers both; `decode(topic, payload, registry)` passes the device's binding to the decoder; `RawRecord.unit` |
| `gateway/mapper.py` | `Binding.registers` (per Modbus value: kind, address, count, data type, byte/word order); start-up check that the data type and register count agree |
| `gateway/normaliser.py` | A unit stated in the message wins over the type's raw unit |
| `gateway/units.py` | V, A, Hz, kWh added (checked on qudt.org) |
| `gateway/demo.py` | Shows all four formats |
| `tests/test_real_formats.py` | 18 new tests |
| `tests/samples/tasmota.json`, `sdm120.json` | Sample messages |
| `requirements.txt` | `tzdata`: Windows has no timezone database built in |
| `contracts/topics.md` | Raw formats table |
| `tools/list_sources.py`, `SOURCES.md` | Source index |

### Decisions

**1. The mapper doubles as the device registry.** Decoders that need instance facts (timezone, register layout) get the device's binding through it. This is the role Hono's device registry plays. The decoders don't import the mapper; they're just handed the binding.

**2. A unit in the message beats the type.** The device knows its own setting; the type only knows the default.

**3. A register the type doesn't describe keeps its raw words** (e.g. `[1, 2]`) and goes to quarantine. It can't be decoded without knowing its type, but it isn't lost.

**4. Borealis also sends a unit per reading (`"unit": "C"`)** but its decoder doesn't pass it on yet. Same idea as Tasmota; left as is because it's a made-up format.

### Try it

```bat
cd v0.1\services\ingestion-gateway
venv\Scripts\activate
pip install -r requirements.txt     :: tzdata is new
python -m pytest                    :: 76 passed
python -m gateway.demo
```

```
raw/modbus/sdm120_unit1/registers
  InputRegister:0 = 236.89999389648438 -> QUARANTINE: unknown point
  InputRegister:12 = 1150.5      -> unit1.power          = 1.1505 KiloW  @ 2026-10-18T10:22:00.000Z
  ...
raw/tasmota/tasmota_zone1/tele/SENSOR
  DS18B20.Temperature = 21.4     -> unit1.zone_air_temp  = 21.4 DEG_C  @ 2026-10-18T10:22:00.000Z
```

`236.89999...` is how a 32-bit float stores 236.9. It is only rounded once it's mapped to a point (normaliser step 4).

### Next: step 2g, validator

As planned before: decide each reading's `quality` (GOOD / SUSPECT / BAD) with plausible ranges stored with the points.

---

## 2026-10-19 · Step 2g: validator (quality flags)

### The job

Decide each reading's `quality`: **GOOD**, **SUSPECT** or **BAD**. The reading itself is never changed or thrown away. A BAD reading is still stored, with its flag, so it can be looked at later. (Quarantine is different: that's for messages the gateway can't *understand*. A BAD reading was understood, it just isn't believable.)

### The pattern: QARTOD

Rather than invent checks, this follows **QARTOD**, the US IOOS standard for quality-checking real-time sensor data, as implemented in their open-source Python library **ioos_qc** (I read its `qartod.py`, version 3.0.0). Its flags map straight onto ours, and onto OPC UA's Good / Uncertain / Bad:

| QARTOD flag | Ours | OPC UA |
|---|---|---|
| 1 pass | GOOD | Good |
| 3 suspect | SUSPECT | Uncertain |
| 4 fail | BAD | Bad |

Each check gives a flag and the **worst one wins** (the same order ioos_qc uses).

### The four checks in this step

| Check | QARTOD test | Fails as | Example |
|---|---|---|---|
| Outside the **sensor's** range | gross range, "fail span" | BAD | DS18B20 says 130 °C; it can only measure -55 to 125 |
| Outside the **expected** range | gross range, "suspect span" | SUSPECT | 2 °C in an occupied room: possible, worth a look |
| Time in the **future** | impossible date | BAD | more than 60 s ahead of when we received it |
| Time too **old** | data reception | BAD | more than 6 h old when it arrived |

### Where the two ranges live, and why there

The two ranges come from different people, so they live in different files:

- **Sensor range**: a fact about the *device model*, from its datasheet. It goes in the **device type**, written with the W3C SSN term for it (`ssn-system:MeasurementRange`, "the set of values that the Sensor can return"), in the same shape as SSN's own DHT22 example. Added for the DS18B20: -55 to 125 °C (Analog Devices datasheet).
- **Expected range**: a judgement about *this point in this building*. It goes on the **asset-model point** (`dtteo:expectedRange`). Added for zone, supply and outside air temperature and power. **These four are placeholders I chose**, marked as such in the file. They need replacing with limits agreed with Botanic, especially the power one (should come from the unit's rated input power).

The mapper reads both at start-up, converts them to the point's unit (so a range written in °F still works), and refuses to start if the expected range goes beyond the sensor range. That's ioos_qc's own rule.

### What I added or changed

| File | Change |
|---|---|
| `gateway/validator.py` | New: `validate()` -> `Verdict(quality, reasons)`; `with_quality()` -> a complete canonical message |
| `gateway/mapper.py` | `PointMapping.fail_span` / `suspect_span`, loaded and unit-converted at start-up |
| `mappings/dtteo_onboarding.ttl` | `dtteo:expectedRange`, and how both ranges are written |
| `mappings/types/tasmota_ds18b20.ttl` | DS18B20 sensor range |
| `dtteo_asset_model.ttl` | Placeholder expected ranges on four points |
| `gateway/demo.py` | Shows the quality |
| `tests/test_validator.py` | 19 tests |

### Decisions

**1. A minute of clock difference is allowed.** QARTOD flags any future time. Real device clocks drift a little, so a reading up to 60 s "ahead" is still GOOD.

**2. The stale limit is 6 hours**, ioos_qc's default. It's right for live data but wrong for a historical CSV import, so it can be switched off (`max_age=None`). The demo does this, because its samples are recorded messages.

**3. The fake vendors get no sensor range.** Acme and Borealis have no datasheet, and inventing one would be exactly the made-up detail we're avoiding. Their readings still get the expected-range and time checks through the asset-model point.

**4. The reasons aren't in the message yet.** The contract only has `quality`. The reasons (e.g. "130 is outside the sensor's range") are returned for logs. Adding them to the message would change the contract; see open question below.

### Not done yet: checks that need history

QARTOD's **spike**, **rate of change** and **flat line** ("stuck sensor") tests, plus duplicate detection, compare a reading with the previous ones from the same point. That needs the gateway to keep a little state per point, so they come after the storage step, when there's somewhere to read recent values from.

### Open question

Should the canonical message carry *why* a reading isn't GOOD (e.g. `"qc": {"gross_range": 3}`, QARTOD style)? It's useful for the twin and for debugging, but it's a contract change (`v` 1 -> 2). My suggestion: not yet. Keep reasons in logs until something downstream needs them.

### Try it

```bat
cd v0.1\services\ingestion-gateway
venv\Scripts\activate
python -m pytest              :: 95 passed
python -m gateway.demo        :: every mapped reading now shows GOOD / SUSPECT / BAD
```

### Next: step 2h, publisher and quarantine

Wire the pieces into the running gateway: subscribe to `raw/#`, run decode -> map -> normalise -> validate, publish canonical messages on `dt/v1/telemetry/...` and anything rejected on `dt/v1/quarantine/...` (with a small, defined quarantine message format).

---

## 2026-10-19 · Step 2h: the running gateway (broker in, broker out)

### The job

Connect everything built so far to the broker, so it actually runs:

```
raw/#  ->  decode -> map -> normalise -> validate  ->  dt/v1/telemetry/site1/{equipment}/{point}
                                                   ->  dt/v1/quarantine/{source}   (couldn't be processed)
```

### Two files, on purpose

| File | Does | Why separate |
|---|---|---|
| `gateway/pipeline.py` | One raw message in -> the list of messages to publish, plus log lines | No MQTT in it, so it's tested without a broker |
| `gateway/service.py` | Connects to the broker, subscribes, publishes what the pipeline returns | Small, and the only part that needs a broker |

### Quarantine vs BAD (the rule, now in code)

- **Quarantine**: the gateway couldn't turn it into a canonical message at all. Three stages: `decode` (whole message unreadable), `map` (field has no point), `normalise` (e.g. a mode word not in the value map).
- **BAD / SUSPECT**: it was understood, but doesn't look right. It's still **published** as a canonical message with its flag, and stored later. Nothing is dropped.

### The quarantine message (new contract)

`contracts/quarantine_message.schema.json`. Follows the dead-letter pattern used by Kafka Connect: keep the **original message untouched** (`raw`) and add **context** (`stage`, `reason`, `field`, `value`, `topic`, `ingest_time`). So once a mapping is fixed, the original can be replayed.

```json
{"v": 1, "stage": "map", "field": "rh", "value": 54.7,
 "reason": "field 'rh': optional, unit1 has no brick:Zone_Air_Humidity_Sensor point, so not mapped (add the point to the asset model to keep it)",
 "topic": "raw/acme/acme_hvac_0001/telemetry", "source": "acme", "device": "acme_hvac_0001",
 "raw": "{\"deviceId\": \"ACME-HVAC-0001\", ...}", "ingest_time": "2026-10-19T13:05:52.346Z"}
```

The reason says **what to fix**: device not bound, binding disabled, field not in the device type, or optional with no point.

### Logs explain each message (as agreed)

One line per event, in `key=value` form ("logfmt"): readable by eye, and searchable by tools later.

```
WARNING quarantine stage=map topic=raw/acme/acme_hvac_0001/telemetry field=rh value=55.5 reason="field 'rh': optional, ..."
INFO    reading point=unit1.zone_air_temp value=93.3333 unit=DEG_C quality=SUSPECT ... reasons="93.3333 is outside the expected range 5.0..35.0"
```

- `WARNING`: every quarantine, with the reason.
- `INFO`: every reading that isn't GOOD, with the validator's reasons. Also start-up notes from the mapper.
- `DEBUG`: every GOOD reading too (`LOG_LEVEL=DEBUG`).

The reasons stay in the logs, not in the canonical message, so the message contract is unchanged (v1).

### Not losing data across restarts (the README's "small buffer")

| What restarts | What happens | Mechanism |
|---|---|---|
| The broker | Gateway keeps unsent QoS 1 messages and sends them after it reconnects (up to 10,000) | paho-mqtt's outgoing queue (I read its `publish` code to confirm) |
| The gateway | Broker keeps raw QoS 1 messages for it until it's back (Mosquitto default: 1,000) | Persistent session (`clean_session=False`) |

Limit: Mosquitto keeps that queue in memory unless its `persistence` setting is on, so a *broker* restart while the gateway is also down loses it. Fine for v0.1; noted for the deployment step.

### Settings (environment variables)

`BROKER_HOST`, `BROKER_PORT`, `GATEWAY_SITE` (default `site1`), `MODEL_DIR`, `GATEWAY_ENABLED` (e.g. `acme_hvac_0001=off,site4_hvac_01=on`), `LOG_LEVEL`. In Docker, the asset model and `mappings/` are mounted read-only, so changing a mapping needs a restart, not a rebuild.

### Checked

- 107 tests pass (12 new in `test_pipeline.py`; every outgoing message is checked against its schema).
- **Live run** against a real (test) MQTT broker: gateway + Acme publisher + a watcher subscribed to `dt/v1/#`. Telemetry, quarantine and online/offline status all arrived as expected:

```
R dt/v1/status/ingestion_gateway online
  dt/v1/telemetry/site1/unit1/zone_air_temp {"v": 1, "point": "unit1.zone_air_temp", "value": 20.6111, ...
  dt/v1/quarantine/acme {"v": 1, "stage": "map", "reason": "...", ...
  dt/v1/telemetry/site1/unit1/mode_status {"v": 1, "point": "unit1.mode_status", "value": "heat", ...
  dt/v1/status/acme_hvac_0001 offline
  dt/v1/status/ingestion_gateway offline
```

### Try it

With Docker (from `v0.1`):

```bat
docker compose --profile acme up --build
:: second terminal
docker compose logs -f gateway
docker compose exec mosquitto mosquitto_sub -v -t "dt/v1/#"
```

To run Borealis instead (Windows `cmd`):

```bat
set GATEWAY_ENABLED=acme_hvac_0001=off,site4_hvac_01=on
docker compose --profile borealis up --build
```

Without Docker (broker already running on your PC):

```bat
cd v0.1\services\ingestion-gateway
venv\Scripts\activate
pip install -r requirements.txt     :: paho-mqtt is new
python -m gateway.service
```

### Stage 2 (ingestion gateway) is complete

Raw data from four formats (two fake, two real) arrives on the broker and leaves as canonical, quality-flagged messages, with quarantine and logs for everything else. What's left in the gateway is later work: QARTOD's history-based checks (after storage), a Modbus poller, a CSV importer, and broker logins/ACL (deployment).
