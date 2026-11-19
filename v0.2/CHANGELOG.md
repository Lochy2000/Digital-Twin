# Changelog

Changes after the tested v0.1 (git tag `v0.1-tested`, the code `experiments/FINDINGS.md` measured).
Fix numbers are FINDINGS section 3. FINDINGS itself is left as the v0.1 evidence.

## v0.2 restructure (18 Nov 2026)

v0.1 split into `common/`, `gateway/`, `platform/`, `dev/` (ADR-003, to write). v0.1 as it was: git tag `v0.1-final`.

### Step A: shared package (no behaviour change)

| What | Why | Files |
|---|---|---|
| New package `dtteo-common`: mapper, units, logfmt (`kv`), Modbus types, contracts | Historian imported gateway code; separate repos need a shared, versioned package (pattern review #8) | `common/` |
| Modbus type table moved from the decoder to `dtteo_common.modbus_types` | The mapper imported the gateway's Modbus decoder | `modbus_types.py`, `mapper.py`, `decoders/modbus.py` |
| `Mapper.from_folder(model_dir, enabled, extra_dirs)` | Load plug-in mappings (test vendors) from another folder | `mapper.py` |
| Decoder plug-ins: `register()`, `load_plugins(folder)`; built-in table is Tasmota + Modbus only | Fake vendors out of the live table (pattern review #7) | `decoders/__init__.py` |
| Acme/Borealis = test plug-ins in `gateway/tests/vendors/` (decoders, types, bindings, samples). Their bindings left `site1.ttl` | Nearly every gateway test uses them as test data | `tests/vendors/`, `bindings/site1.ttl` |
| `GATEWAY_PLUGINS` setting; `MODEL_DIR` default is now `gateway/model` | Dev setup loads the vendors; the Pi doesn't | `service.py` |
| Tests find files through `tests/support.py`; mapper tests moved to the gateway (they test its model files) | v0.1 tests climbed up to the v0.1 folder | `gateway/tests/` |
| Historian: `dtteo_common` instead of `gateway.*`; contracts from the package | No gateway code in the platform | `platform/historian/` |

**Checked:** common 12 passed + contract examples OK · gateway 118 passed (v0.1's tests + new tests for
plug-ins and that the Pi build binds no fake vendors) · historian 7 passed, 9 skipped (database tests need
`TEST_DATABASE_URL`, as in v0.1) · `python -m gateway.demo` runs.

### Step B: split the Docker setup (no behaviour change)

| What | Why | Files |
|---|---|---|
| `gateway/compose.yml`: broker (`gateway-broker`) + gateway | Runs on the Pi on its own | `gateway/compose.yml`, `.env.example` |
| `platform/compose.yml`: TimescaleDB, migrate, historian, Grafana, backup | Runs on the server on its own | `platform/compose.yml`, `.env.example` |
| `dev/compose.yml` *includes* both, plus Acme/Borealis; `gateway.dev.yml` adds the plug-ins, `platform.dev.yml` points the historian at the gateway's broker | One command on the laptop, without copying the other two files | `dev/` |
| Dockerfiles build from `v0.2/` and install `common` (normal install) | Images need the shared package | `gateway/Dockerfile`, `platform/historian/Dockerfile`, `.dockerignore` |
| No `container_name`; project names `dt-gateway`, `dt-platform`, `dtteo-dev` | No clash with v0.1's containers; v0.2 gets its own fresh volumes | compose files |
| Smoke test finds `dev/.env`, `gateway-broker`, `platform/storage/migrations` | New layout | `dev/smoke_test.py` |

**Checked here:** `docker compose config` for dev (with Acme), gateway alone and platform alone (paths,
passwords, volumes) · the build context holds no `.env`, backups or tests · `common` installs normally with
its schemas · gateway service run live against a real Mosquitto broker with the plug-ins: Acme message ->
`unit1.zone_air_temp` 21.1111 °C GOOD, `mode_status` "cool", unknown `co2` quarantined.
**Not possible here (Docker Hub blocked):** building images and running the stack; that's the laptop run.

**Known gap until step E:** the platform has no broker of its own, so `platform/` alone waits for one.

### Step C: the lab rig through the gateway

| What | Why | Files |
|---|---|---|
| **C1** `Settings`: every gateway setting read and checked once at start-up; all problems reported together; password never logged | Settings were read with `os.getenv` all over the service, so typos showed up late (pattern review #9) | `gateway/settings.py`, `service.py` |
| **C2** dt-edge decoder `dtedge`: `raw/dtedge/{node}/telemetry`, one reading or a list | dt-edge's message looks canonical but isn't (`point_id` not `point`, `+00:00` not `Z`, `qc` as plain words), so it is decoded like any device | `decoders/dtedge.py`, `contracts/topics.md` |
| Device type `dtedge_rig` (29 fields), binding `digitwin_pi` -> `:rig1`, 29 `rig1.*` points (thermocouples 1-8 + logger, Lepton/MLX max/mean/min, Lepton spots 1-8, room air/humidity/pressure, plug power/energy/on) | The rig's sensors, named by what they are on (`rig1.tc_ch1`), not by sensor; kettle or matrix stays in dt-edge's asset profiles | `model/...`, `platform/dtteo_asset_model.ttl` (copy) |
| Device's own quality kept as check `device_flag` (SUSPECT/BAD); gateway checks still run | dt-edge already knows about dead pixels etc. Not thrown away, not trusted alone | `decoders/__init__.py` (RawRecord), `validator.py`, `pipeline.py` |
| **Contract:** `device_flag` added to the allowed `qc[].test` names; `dtteo-common` 0.2.1 (`v` stays 2) | New check name; every old message is still valid | `canonical_message.schema.json`, `contracts/NOTES.md` |
| A `null` value is quarantined ("no value") | dt-edge sends null for a failed read | `normaliser.py` |
| Units `PA`, `HectoPA`, `PERCENT_RH` (QUDT multipliers 1, 100, 0.01) | BME280 pressure and humidity | `dtteo_common/units.py` |
| Broker login `digitwin_pi` (test-device password for now) | So the Pi can publish | `gateway/broker/start.sh` |
| **C3** `dev/replay_run.py`: a dt-edge run (either download: "All readings" or "Excel CSV", one or several parts) offline through the pipeline with a summary, or `--publish` to the dev broker | Test with real recordings before dt-edge publishes live | `dev/replay_run.py` |
| Smoke test check 9: gateway and platform asset-model copies match | The copy (ADR-003) must not drift | `dev/smoke_test.py` |

Placeholders, to replace: the rig's expected ranges (lab guesses); the sensor ranges in `dtedge_rig.ttl`
are datasheet values marked TO VERIFY.

**Checked here:** gateway 138 passed (16 new: decoder, rig pipeline, settings) · common 12 · historian 7 + 9 skipped ·
model loads with 31 field mappings · a model mistake was caught at start-up as designed (Lepton expected range
below its sensor range) · synthetic 2-part, 6,302-row dt-edge recording: offline 6,300 stored / 2 quarantined /
0 contract breaks; the same through a real Mosquitto broker + the gateway service: 6,300 telemetry + 2 quarantine.

**Matrix cool-down run (8-9 Nov, 3 Excel-CSV parts), offline replay:** 278,913 readings over 3.70 h, all 21 sensor
columns mapped, 0 quarantined, 0 contract breaks. 1 reading BAD: `rig1.lepton_min` -10.49 degC at 01:11:27, below
the Lepton's -10 degC datasheet limit (marked TO VERIFY). Check that limit before relying on BAD for the cameras.

**Not yet:** dt-edge doesn't publish over MQTT yet (dt-edge change, later); thermal images (later, with the Pi Zero nodes).

## Quick fixes (made in v0.1 on 5 Nov, before the restructure)

### Quick wins (5 Nov 2026)

| Fix | What changed | File | Checked here | Still to re-check on the lab PC |
|---|---|---|---|---|
| 3 NaN/Infinity | Normaliser sends any non-finite number to quarantine (`math.isfinite`), for every point | `gateway/normaliser.py` | 3 new pipeline tests (NaN, Infinity, -Infinity) fail on old code, pass on new. 124/124 gateway tests pass | E1 storage checks |
| 9 PressureUnit | Tasmota decoder treats `PressureUnit` as a label, like `TempUnit` | `gateway/decoders/tasmota.py` | New BME280-shaped test | E7 |
| 5 Delay | Historian `BATCH_SECONDS` default 1.0 → 0.2; broker `set_tcp_nodelay true` | `historian/service.py`, `broker/mosquitto.conf` | Broker starts with the setting | E2 (expect p99 ≈ 0.2–0.3 s) |
| 1 Broker crash | Broker saves after every change (`autosave_on_changes true`, `autosave_interval 1`) instead of every 60 s | `broker/mosquitto.conf` | Mini crash test (Mosquitto 2.0.18): 5 messages queued for an absent client, then `kill -9`. Old config: 0/5 kept, 3 runs. New: 5/5, 3 runs | E4 broker-crash scenarios; E2/E3 for the cost of saving so often |

**Notes**
- **Fix 1 is a lab-rate setting.** Each save rewrites the whole snapshot. That's cheap with ~10 points, but costly with a big backlog or thousands of messages a second. The scale path is Mosquitto 2.1's SQLite persistence, which is an upgrade (new image tag, deprecated `acl_file`/`password_file`), not a setting.
- **Fix 9 does not use `PressureUnit` as the pressure's unit yet.** No point in the model stores pressure. When one is added, handle it the way `TempUnit` is handled.
- To apply: `docker compose up -d --build` (rebuilds gateway and historian, restarts the broker with the new config).

### Not started
2 gateway manual ack · 4 stateful checks · 6 energy-per-hour aggregate · 7 completeness view · 8 TLS + per-device passwords · 10 clock offset
