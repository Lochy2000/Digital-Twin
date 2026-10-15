# services/ingestion-gateway/: developer notes

The gateway is the system's front door: raw device data comes in, canonical messages go out (see `../../contracts/`). It is being built one piece at a time, in the order of the D-03 diagram. Newest entry at the bottom.

```
adapter (decode) → MAPPER → normaliser → validator → publisher
                     ▲ built in this step
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
- **B. The semantic model itself.** ✅ Chosen.

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
