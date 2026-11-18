# Changelog

Changes after the tested v0.1 (git tag `v0.1-tested`, the code `experiments/FINDINGS.md` measured).
Fix numbers are FINDINGS section 3. FINDINGS itself is left as the v0.1 evidence.

## v0.2 (in progress)

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
