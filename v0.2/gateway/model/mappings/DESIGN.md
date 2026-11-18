# Onboarding design: device types and device bindings

**Status:** built in step 2e (2026-10-16); see `services/ingestion-gateway/NOTES.md`. Sources re-checked on 2026-10-16; see *Verification log* at the end.

**Changes made while building:** the type names a value's **Brick class** (not a role name), and the mapper finds the point of that class on the bound equipment. Bindings gained `dtteo:place` (for generic sensors such as a temperature probe, whose meaning depends on where it's installed) and `dtteo:enabled` (to swap which device feeds a point). The check is `python -m gateway.mapper` rather than a separate command. Two real formats were added as test cases: Tasmota on an ESP8266, and the Eastron SDM120 Modbus meter.

**Problem:** today every mapping is written per individual device. With 20 identical units, the same vendor knowledge would be copied 20 times. The design must also work for real sources, not just the two fake vendors.

---

## 1. Patterns this is based on

Rather than inventing something, the design combines four established patterns:

| Pattern | Where it comes from | What we take from it |
|---|---|---|
| **Template vs instance** | W3C Web of Things: "A Thing Model is a description for a class of Things that have the same capabilities", and it lacks the detail needed to identify or reach one particular Thing. It can be used "as template for creating Thing Description instances", e.g. for "large-scale production of new devices". TD 1.1 §9.1 compares it to an abstract class (the model) and objects (the descriptions). Eclipse Ditto builds new Things from Thing Models. ThingsBoard calls the template a *device profile*; AWS SiteWise calls it an *asset model*. | Vendor and model knowledge is written **once per device type**. |
| **Describing Modbus registers** | W3C WoT Modbus binding (`modv:` terms). The **OPC UA WoT Connectivity** spec (OPC 10100-1) onboards industrial assets with it; its example is a Siemens PAC4200 meter with a voltage register (`modv:entity`, `modv:type xsd:float`, `modv:pollingTime`). | We use the same terms for register-based devices, so a WoT export is possible later. |
| **Binding a data stream to an asset property** | AWS SiteWise: a device's data stream is associated with an asset property, and "an asset property can only be linked to one data stream at a time". | Each device is **bound to the equipment it serves**, and each point has **one live source** at a time. |
| **Per-point external references** | Brick's `ref:BACnetReference` and `ref:TimeseriesReference` (already used in step 2b). BuildingMOTIF maps irregular BMS point labels to Brick point by point. | Irregular sources such as BMS exports keep **per-field** bindings, because a template doesn't help there. |

---

## 2. The two pieces

### Device type: what a model of device sends, written once

"Every Acme HVAC unit sends `tempF` (Fahrenheit) as the zone air temperature, and `op_state` as its mode, where 2 means cool."

A device type describes, for each value the device sends:
- **where it is** in that device's data: a JSON key, a CSV column, or a Modbus register;
- **what it is:** a *role* (e.g. `zone_air_temp`) plus its Brick class and unit;
- **how to read it:** raw unit, scale, value map;
- whether the value is **optional**, i.e. some installed units of this model may not have it (e.g. an optional power meter). WoT does the same with `tm:optional` (TD 1.1 §9.3.4);
- a **version** number, so a changed type is visible. WoT recommends this for Thing Models (`version.model`, semantic versioning, §9.3.1).

It says nothing about any particular installed device: no IP address, no serial number, no "which unit". This matches WoT, where a Thing Model "does not contain Thing instance-specific information" (§9.1).

### Device binding: this device is this one, here

"Device `acme_hvac_0002` is an *Acme HVAC* and serves `unit2`."

One short entry per installed device:
- which **device type** it is: exactly one. WoT has the same rule: a Thing Description "can only be an instance of one TM at a time" (§9.4);
- which **equipment** in the asset model it serves;
- how to **reach it**, if we have to fetch its data (a Modbus host and unit ID; nothing extra for MQTT devices that push).

### How the gateway combines them

```
message from acme_hvac_0002, field "tempF"
   binding:     acme_hvac_0002 -> type acme_hvac, equipment unit2
   type:        tempF -> role zone_air_temp, raw unit DEG_F
   point ID:    unit2 + zone_air_temp = unit2.zone_air_temp
```

The gateway still builds the **same lookup table** as today (`(source, device, field) → point`). Only *where it gets the information from* changes, so the decoders, normaliser and everything downstream are untouched.

---

## 3. Tested on paper against four different sources

### A. Acme HVAC unit: JSON over MQTT, device pushes

| Device type `acme_hvac` | | |
|---|---|---|
| field `tempF` | role `zone_air_temp` | raw unit DEG_F |
| field `op_state` | role `mode_status` | value map 1=heat, 2=cool, 3=off |

Bindings: `acme_hvac_0001 → unit1`, `acme_hvac_0002 → unit2`, and so on.

**Fits.** Adding a unit is one binding line.

### B. Modbus heat pump: registers, we poll it

Values come from the manufacturer's register map (this example is illustrative, not a real product). Following the W3C Modbus binding, each value is described by the register **kind** (`modv:entity`), its **address**, how many registers it spans (`modv:quantity`), its **data type** (`modv:type`) and, for multi-register values, its **byte and word order** (`modv:mostSignificantByte`, `modv:mostSignificantWord`):

| Device type `example_heat_pump` | | | |
|---|---|---|---|
| InputRegister, address 0, quantity 1, `xsd:short` | role `supply_air_temp` | scale 0.1 | DEG_C |
| InputRegister, address 9, quantity 2, `xsd:int`, word-swapped | role `power` | raw unit W | to KiloW |
| HoldingRegister, address 0, quantity 1, `xsd:unsignedShort` | role `mode_status` | value map 0=off, 1=heat, 2=cool | |

Binding: `hp_plantroom → unit1`, reached at `modbus+tcp://192.168.1.50:502/1` (host, port, unit ID 1), poll every 30 s.

Two points from the spec are reflected here:
- **Register numbers like 30001 or 40001 are a community convention, not part of Modbus or the W3C spec.** The spec says the description should give the address to use directly, with the register kind stated separately. Manufacturers' manuals often use the 30001-style numbers, so whoever writes a type must convert them once, when copying from the manual.
- **Byte and word order vary between manufacturers.** The spec notes word swapping "is not part of the Modbus specification but is common in off-the-shelf devices". Getting it wrong produces nonsense numbers, so it must be stated in the type, never assumed.

**Fits.** The W3C spec builds each register's location from two parts: a **base** URL for the device (`modbus+tcp://host:port/unitID`) and a **relative** address per value (e.g. `9?quantity=2`). That maps neatly onto our split. The per-value part is the same for every unit of that model, so it goes in the **type**. The base URL differs per installed unit, so it goes in the **binding**. That matches how WoT separates a Thing Model (no instance or communication detail) from a Thing Description (has it). The field name is the register location (e.g. `InputRegister:9`), so the mapper and normaliser don't change. Scale (step 2d) is exactly what Modbus needs; decoding the raw bytes using `modv:type` and the byte order will be the Modbus decoder's job.

### C. BMS CSV export: many units in one file, irregular names

```
Timestamp,         AHU-1 SAT, Zone 1 Temp, Zone 2 Temp, HP-2 kW
2026-03-01 14:00,  18.2,      21.5,        20.9,        3.4
```

**A template doesn't help here.** Column names are specific to that one site's BMS, and one file covers several units. So this source uses **per-field bindings**, the same mechanism we have today, which matches how Brick and BuildingMOTIF handle irregular BMS labels:

| Field (column) | Point |
|---|---|
| `Zone 1 Temp` | `unit1.zone_air_temp` |
| `Zone 2 Temp` | `unit2.zone_air_temp` |
| `HP-2 kW` | `unit2.power` |
| `AHU-1 SAT` | *(not bound, so quarantined)* |

The binding also states the file's timestamp column and **its timezone**, because BMS exports often use local time with no offset (the step 2c rule: never guess the timezone).

**Fits, using the per-field route.** Both routes produce the same lookup table.

### D. Borealis

The same as A: device type `borealis_hvac`, plus one binding.

### Summary

| Source | Route | Adding another one means |
|---|---|---|
| Identical devices (Acme, Modbus heat pump) | Type + binding | one binding |
| Irregular one-off source (BMS export) | Per-field bindings | one line per field |
| A completely new model | New type (+ a decoder only if it's a new *format*) | one type file |

---

## 4. Rules the gateway checks at start-up

1. **Every binding names exactly one type that exists**, and **equipment that exists in the asset model.**
2. **Every required role in a type maps to a point the equipment actually has.** If `unit2` has no `zone_air_temp` in the asset model, start-up fails. This catches "forgot to add it to the asset model". Roles marked optional may be missing; the check reports them but doesn't fail.
3. **One live source per point** (SiteWise's rule). Two bindings feeding `unit1.zone_air_temp` is an error, not a silent mix of two streams. Swapping Acme for Borealis means changing one binding.
4. As today: a field bound to two points is an error.

A single command, `python -m gateway.mapper`, runs all of these and prints a plain report, so "did I add it everywhere?" is answered by the tool.

---

## 5. What changes, and what doesn't

| Part | Change |
|---|---|
| Decoders, normaliser, contract, topics | **None** |
| Mapper | Builds its lookup table from types + bindings + per-field bindings, instead of per-device mappings only |
| `mappings/` folder | Split into `types/` (one file per device model) and `bindings/` (installed devices and per-field mappings) |
| Asset model | Unchanged for now. **Later option:** generate an equipment's points automatically from its device type when a device is bound. Ditto and BuildingMOTIF both generate model parts from templates. |
| Later, if needed | **Type families:** a type can extend another (WoT `tm:extends`, §9.3.2), e.g. model B = model A plus two registers. WoT only allows an extension to *narrow* the original (e.g. a smaller allowed range), never widen it. **Composed equipment:** a heat pump with a separate power meter could be two types combined (WoT `tm:submodel`, §9.3.3). Neither is needed for v0.1. |

**File format:** stay in Turtle, the same as the asset model, so everything is one graph, validated by Brick and queried the same way. For register details we use the W3C WoT `modv:` term names, so a WoT Thing Model export stays possible later.

**Where this design follows WoT, and where it mixes patterns.**
- **Follows WoT:** the WoT Thing Model chapter (TD 1.1 §9) defines exactly this template/instance split. A Thing Model may even hold the connection details as **placeholders**, written `{{NAME}}`, e.g. `"base": "mqtt://{{MQTT_BROKER_ADDRESS}}"`, which are filled in when an instance is created (§9.3.5). §9.4 lists the steps to turn a model into a description: copy the model, resolve imports, drop optional parts not used, replace placeholders, add the missing connection and security details. Our **binding** is the set of values that fill in those blanks.
- **Our combination:** the W3C Modbus binding and the OPC UA WoT Connectivity spec both work with **one description per installed device**. The OPC UA spec's onboarding uploads a Thing Description that "fully defines the endpoint, protocol, and all asset tags" for that one asset. Neither shows a Modbus *Thing Model* as a worked example, so putting a register map into a reusable type is our combination of the two specs. It is allowed by both, just not demonstrated.
- **Our own additions:** value maps and scale. WoT can list the allowed values (`enum`) but has no translation table such as "2 means cool".

---

## 6. Open questions for review

1. **One live source per point** means Acme and Borealis can't both feed `unit1` at once (they would be bound to different equipment, or only one bound at a time). Is that acceptable for testing? I think yes; it is how a real site works.
2. **Should onboarding generate asset model entries automatically**, or stay manual with the check command for now? Recommendation: manual plus check for v0.1, generation later.
3. **Modbus and CSV transports** are not built yet. This design only makes sure the *mapping* side won't need redoing when they are.

---

## Sources

- W3C WoT Thing Description 1.1, §9 Thing Model: <https://www.w3.org/TR/wot-thing-description11/#thing-model>
- W3C WoT Thing Model ontology (definition of a Thing Model): <https://www.w3.org/2022/wot/tm>
- W3C WoT Binding Templates: <https://www.w3.org/TR/wot-binding-templates/>
- W3C WoT Modbus binding (`modv:` terms, addressing, byte/word order; work in progress): <https://w3c.github.io/wot-binding-templates/bindings/protocols/modbus/index.html>
- node-wot Modbus binding (reference implementation): <https://cdn.jsdelivr.net/npm/@node-wot/binding-modbus@0.9.2/README.md>
- OPC UA WoT Connectivity (OPC 10100-1), §6.1 example and §6.3.2 CreateAsset: <https://reference.opcfoundation.org/WoT/v100/docs/6.1>, <https://reference.opcfoundation.org/WoT/v100/docs/6.3.2>
- Eclipse Ditto WoT integration: <https://eclipse.dev/ditto/basic-wot-integration.html>
- ThingsBoard device profiles: <https://thingsboard.io/docs/user-guide/device-profiles/>
- AWS IoT SiteWise asset models: <https://docs.aws.amazon.com/iot-sitewise/latest/userguide/create-asset-models.html>
- AWS IoT SiteWise data streams and aliases: <https://docs.aws.amazon.com/iot-sitewise/latest/userguide/data-streams.html>
- BuildingMOTIF templates: <https://buildingmotif.readthedocs.io/en/latest/explanations/templates.html>
- BuildingMOTIF BACnet to Brick (label mapping): <https://buildingmotif.readthedocs.io/en/latest/guides/ingress-bacnet-to-brick.html>

---

## Verification log (2026-10-16)

On a second, more careful read of the sources:

| Source | What was checked | Result |
|---|---|---|
| W3C WoT Modbus binding | Full term list, addressing, data types, byte/word order, examples | **Corrected the design:** register numbers like 30001 are a convention, not part of the spec; added register kind, data type and byte/word order to the Modbus example. The spec is marked *work in progress* and doesn't cover templates. |
| W3C WoT Thing Model ontology | Definition of a Thing Model | Confirms: "a description for a class of Things that have the same capabilities", usable as a template for Thing Descriptions. (The ontology also lists `tm:required`; TD 1.1 uses its inverse, `tm:optional`.) |
| W3C WoT Thing Description 1.1, §9 Thing Model (9.1 to 9.5) | Read in full in a browser (the web-fetch tool's copy stopped in §5) | **Confirms** the type/binding split (§9.1, no instance-specific information in a model) and one type per instance (§9.4). **Changed the design:** added optional values (`tm:optional`) and a version per type, and softened rule 2 so optional roles don't fail start-up. **Clarified:** WoT does define templates, with placeholders filled per instance (§9.3.5), so the template idea itself is WoT, not our invention. Type families (`tm:extends`) and composition (`tm:submodel`) noted as later options. |
| OPC UA WoT Connectivity, §6.1 and §6.3.2 | Example TD, how assets are created | Confirms the Modbus example and `modv:` usage. **Clarified the design:** onboarding there is one Thing Description per asset, not templates, so our type/binding split is a combination, now stated explicitly. |
| AWS SiteWise data streams | One data stream per asset property | Confirmed: "an asset property can only be linked to one data stream at a time" |
| ThingsBoard, Eclipse Ditto, BuildingMOTIF | Device profiles, Thing creation from models, templates | Confirmed as described |
