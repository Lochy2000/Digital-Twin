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

### dt-node, first version (19 Nov 2026)

New part `node/` (becomes `dt-node`): runs on each sensor device, reads its sensors, sends to the broker.

| What | Why |
|---|---|
| One thread per sensor; adapters `simulated` (heating/cooling curves) and `csv` (replays a recorded run live) | Build and test without hardware; real sensor adapters come from dt-edge |
| Outbox: every poll goes into a SQLite file first, removed only when the broker confirms it | Nothing lost when the broker or Wi-Fi drops, or the node loses power |
| Reconnect at least every 5 s (paho's own wait grows to 120 s) | Found in the outage test: with the default, the outbox kept filling long after the broker was back |
| Settings in `node.toml` (Python reads TOML itself); password from env | One package needed (`paho-mqtt`): light enough for a Pi Zero |
| Online/offline on `dt/v1/status/{node}`, Last Will | Same as every other client |
| Dev: `--profile node` runs a simulated node posing as the rig's Pi (`digitwin_pi`) | rig1.* data in the dev setup without hardware; default setup and smoke test unchanged |

**Checked here:** 15 node tests. Live, with a real Mosquitto broker and the gateway service: broker stopped for
15 s while the node ran; 44 polls waited in the outbox; the node reconnected 2 s after the broker returned and
sent them oldest first; every field arrived with no gap bigger than its poll interval (0.5 s / 1 s); the gateway
stored all of it as GOOD rig1 readings; outbox empty afterwards. Also found and fixed: stopping the node while
disconnected crashed it. Every field in `dev/node.dev.toml` maps to a rig1 point (11 readings, 0 quarantined).

### Docker builds copy `common` instead of installing it (19 Nov 2026)

A build failed when downloading setuptools timed out (3.6 kB/s). Installing `common` needed build
tools fetched from the internet every time; copying its files needs nothing. Builds now work offline.
`rdflib` is listed in each service's requirements again. Checked: both image layouts rebuilt here
under Python 3.11 with nothing installed but the requirements: gateway pipeline builds (31 mappings),
historian validator builds and reads the platform model (39 points).

### dt-broker in its own folder (19 Nov 2026)

| What | Why | Files |
|---|---|---|
| `broker/`: Mosquitto config, access rules and start script moved out of the gateway; its own compose file | The broker is shared by every part (nodes, gateway, dashboards, historian), so it isn't the gateway's | `broker/` |
| Device logins listed in `.env` (`MQTT_DEVICES`), not in the script | Adding a node = one line of config | `broker/start.sh`, `.env.example` files |
| Gateway runs no broker; connects to `BROKER_HOST` (default: the broker on the same machine) | Gateway and broker deploy separately | `gateway/compose.yml`, `.env.example` |
| Node topics added: telemetry and status (in use), frames and settings (reserved); nodes may read their own settings topic | Message design for dt-node | `contracts/topics.md`, `broker/acl.conf` |
| Dev setup includes `broker/`; services use `broker` | | `dev/` |

**Checked here:** dev, broker, gateway and platform compose files all resolve; the real start script + config on
a live Mosquitto: listed devices get logins, a node publishes to its own topics and status only, anonymous and
unlisted clients refused.

### Step D1: gateway acknowledges only after its outputs are safe (20 Nov 2026) — FINDINGS fix 2

| What | Why | Files |
|---|---|---|
| Manual acks: a raw message is acknowledged only after the broker has confirmed every output made from it; acks go out in arrival order (MQTT 5.0 §4.6) | paho acked on return from `on_message` while outputs still waited in memory, so a crash lost them | new `gateway/acks.py`, `service.py` |
| `RECEIVE_MAX = 100` sent on connect | Caps how many raw messages can wait for an ack, so outputs in memory stay bounded | `service.py` |
| `send()` returns the output's id (or `None` if paho refused it) | The tracker needs the ids to wait for | `service.py` |
| After a reconnect, unacked messages are forgotten and the broker re-sends them | Acks are only valid on the connection a message arrived on; re-sent readings are skipped by the historian's unique key | `acks.py` |

**Checked:** gateway 146 passed (6 new tracker tests, 2 new `send` tests). Kill test (local Mosquitto, simulated
node at 50 polls/s, gateway away 8 s then `kill -9` while draining the backlog, 5 times per run):

| Gateway | Kill after | Readings sent | Missing |
|---|---|---|---|
| before | 0.5 s | 12,132 | **4,792** |
| before | 0.7 s | 12,336 | **1,319** |
| before | 0.9 s | 12,536 | 0 |
| after | 0.3 / 0.5 / 0.7 / 0.9 s | 11,936–12,536 | **0** in every run |

One "after" run re-counted: 102 re-sent copies, proving the kills landed mid-message and were recovered.
Copies of readings are skipped by the historian; a re-sent message that was quarantined is stored twice in
`quarantine` (no unique key there; acceptable for now).

### Step D2: health heartbeat for the gateway and historian (20 Nov 2026)

| What | Why | Files |
|---|---|---|
| Heartbeat every 30 s on `dt/v1/health/{name}` (retained): `ok`, `problems`, counters | `online` stays retained while a service is stuck or its machine is asleep | new `common/dtteo_common/health.py`, `topics.md` |
| Same message written to `/tmp/health.json`; Docker `HEALTHCHECK` runs `python -m dtteo_common.health` (healthy = under 90 s old and ok) | Docker shows `(healthy)` / `(unhealthy)` without a web server or extra port | both `Dockerfile`s |
| Gateway unhealthy when: not connected, broker confirmed nothing for 75 s, or a raw message waited over 60 s for its ack | Running but stuck looked the same as working | `gateway/service.py`, `acks.py` |
| Historian unhealthy when: not connected, broker silent 75 s, database unavailable, or messages waiting with nothing stored for 60 s | Database outages only showed in the log | `historian/service.py` |
| Broker: every login may write its own `dt/v1/health/%u` | Needed to publish heartbeats | `broker/acl.conf` |
| Gateway reconnect wait capped at 5 s (was paho's default, up to 120 s) | Found in the D2 test: 31 s to reconnect after the broker returned. Same fix as the node | `gateway/service.py` |
| Gateway stop (SIGTERM) runs in its own thread | Found in the D2 test: stopping under load crashed (`OrderedDict mutated during iteration`), because the signal interrupted paho's own loop. Nothing was lost (unacked messages are re-sent) | `gateway/service.py` |
| `HEALTH_FILE` setting (`off` = no file) | Running outside Docker, e.g. on Windows, where there's no `/tmp` | `gateway/settings.py`, historian |
| dtteo-common 0.2.2 | New module | `common/pyproject.toml` |

**Checked:** common 17 passed (5 new) · gateway 148 passed (2 new) · historian 10 passed, 9 skipped (3 new).
Live gateway test (local Mosquitto, simulated node at 50 polls/s): healthy at the first full beat ·
broker stopped → unhealthy "not connected" at the next beat · broker back → reconnected in 4 s, healthy at
the next beat · gateway frozen (`SIGSTOP`) → Docker check fails "last heartbeat 103s ago"; on resume it
reports "95 raw messages waiting for an ack" · stop under load → clean exit 0. Historian with no database:
"database unavailable for 30s" at the second beat. Database-down test with the real stack: on the lab PC.

**Notes**
- Docker only *reports* unhealthy; `restart: unless-stopped` doesn't act on it. Restarting automatically
  (e.g. an autoheal container or systemd) is a later decision.
- Heartbeats aren't queued while disconnected, so an old one can't arrive later looking current.

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
~~2 gateway manual ack~~ (done, step D1) · 4 stateful checks · 6 energy-per-hour aggregate · 7 completeness view · 8 TLS + per-device passwords · 10 clock offset
