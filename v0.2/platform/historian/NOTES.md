# services/historian/: developer notes

Design and reasons: `decisions/ADR-002-database-layout.md`, section 7. These notes record what was built.

---

## 2026-10-29 · Stage 3b: the historian

### What it does

Subscribes to `dt/v1/telemetry/#` and `dt/v1/quarantine/#` and writes them into the database, in batches (every 1 s or 500 messages, one transaction each).

| File | Does |
|---|---|
| `historian/store.py` | Messages → rows. No MQTT inside, so it's tested on its own (like the gateway's `pipeline.py`) |
| `historian/service.py` | Broker side: MQTT 5 session, batching, acknowledging, retrying |

At start-up it copies the asset model's points into the `series` table, using the gateway's own `Mapper.points()` (one source of truth; the Docker image includes the gateway's code for this).

### Where each message goes

| Message | Goes to |
|---|---|
| Valid canonical message, known site + point | `readings` (same site + point + time already there → skipped) |
| Quarantine message from the gateway | `quarantine` (stage as sent) |
| Not JSON, fails its contract (`contracts/*.schema.json`), or unknown site/point | `quarantine`, stage `store`, with the reason and the original |
| A row the database refuses (e.g. a NUL character in text) | Batch retried one by one; that message → `quarantine`, stage `store`. One bad message can't block the rest |

### Not losing data

- **Acknowledged only after the database commits** (paho's manual acknowledgement). A crash before that: the broker re-sends, duplicates are skipped.
- **Database down:** the batch is kept, retried at 1, 2, 4 ... 30 s, nothing acknowledged. The broker stops sending at 1,000 unacknowledged messages (MQTT 5 Receive Maximum) and holds the rest.
- **Reconnect to the broker:** messages from the old connection are written but not acknowledged (their IDs only meant something on that connection); the broker re-sends them and the copies are skipped.

### Run it

With Docker it starts with the stack (`docker compose up -d --build`); `docker compose logs -f historian` shows one summary a minute, plus a line for anything unusual.

Tests (from `v0.1\services\historian`, venv active, `pip install -r requirements-dev.txt`):

```bat
python -m pytest
```

The database tests are skipped unless `TEST_DATABASE_URL` points at a database with the migrations applied, as its owner. **They empty the tables first**, so don't point them at data you want to keep.

### Checked

16 tests pass (7 without a database). Live, against real Mosquitto, the gateway and PostgreSQL 16 (TimescaleDB and the Docker image couldn't be pulled in the build environment):

| Test | Result |
|---|---|
| 5 Acme messages | 10 readings + 5 quarantine rows (the unmapped humidity field) |
| Database stopped, 1,500 messages sent, database restarted | Historian held 93 + 907 waiting = **1,000**, the Receive Maximum, so Mosquitto 2.0 honours it; afterwards all **3,000 readings stored** |
| Historian stopped (SIGTERM), 4 messages sent, restarted | Stopped cleanly; session resumed; all 8 readings stored |

**Still to check on your PC:** `docker compose up -d --build` builds the historian image and it connects to TimescaleDB.

### Next

Summaries (ADR-002 section 5) and Grafana, now there's somewhere for data to land.
