# ADR-002: Database layout, and how data gets in, out and backed up

**Status:** Accepted, 29 October 2026, for the feasibility study (PostgreSQL 18; backups local for now). Proposed 28 October 2026.
**Builds on:** [ADR-001](ADR-001-time-series-store.md) (PostgreSQL + TimescaleDB, accepted 19 Oct 2026). This record refines ADR-001's decision item 1 (the table shape) and adds the operating details ADR-001 left open.

*Everything below is a proposal for the feasibility study. The SQL is a sketch to show the shape; the exact SQL is written and tested in the build step, with notes, one piece at a time.*

---

## 1. The question

ADR-001 chose the database. This record decides:

1. **What tables** hold readings, and how a reading is identified.
2. **How each kind of point is summarised** (averages don't suit every point).
3. **How the schema is created and changed** over time.
4. **How the historian writes** without losing or doubling data.
5. **Who can do what** in the database.
6. **How it is backed up** and restored.
7. **How bulk history (CSV)** gets in.

---

## 2. What changed since ADR-001 (inputs to this record)

The gateway was updated first (steps 2i to 2k, `services/ingestion-gateway/NOTES.md`), so storage gets what it needs from every message:

| From the gateway | Why storage needs it |
|---|---|
| `site` in every message | Point IDs are unique only within a site. `site` + `point` is the reading's identity |
| `time_source` (`device` / `gateway`) | Readings stamped by the gateway can't be de-duplicated by time; analysis should know which times to trust |
| `qc` list on non-GOOD readings | So a stored BAD or SUSPECT reading says why |
| `dtteo:valueKind` on every asset-model point (`measurement` / `total` / `state`) | Decides how a point is summarised (section 5) |
| Broker persistence + gateway on MQTT 5 | The historian can rely on the broker holding messages while it's down |

---

## 3. Tables

### 3.1 The pattern: a series table plus one narrow readings table

**Series** = one stream of readings, here one `site` + `point`. Its details (unit, Brick class, kind) change rarely, so they're stored **once** in a small ordinary table. Each reading row just points to it with a number (`series_id`).

Tiger Data, the company behind TimescaleDB, recommends exactly this: keep series details in a separate metadata table and store only a `series_id` in the hypertable. Their reasons: otherwise you are "massively duplicating information", series details can change, and you can find series without scanning the readings ([best practices for time-series metadata tables](https://www.tigerdata.com/blog/best-practices-for-time-series-metadata-tables/)). It's also how Azure Digital Twins' data history works: one narrow table of twin ID, property, value and two times ([data history](https://learn.microsoft.com/azure/digital-twins/concepts-data-history)), as ADR-001 noted.

```
series (ordinary table, ~10 rows now)            readings (hypertable, one row per reading)
┌────────────┬─────────┬──────────────────┐      ┌───────────┬──────────────────────────┬───────┬─────────┐
│ series_id  │ site    │ point_id         │ ◄─── │ series_id │ sensor_time              │ value │ quality │ ...
│ 1          │ site1   │ unit1.zone_air.. │      │ 1         │ 2026-10-28 22:34:50.684Z │ 21.67 │ GOOD    │
│ 2          │ site1   │ unit1.energy     │      │ 2         │ 2026-10-28 22:34:50.700Z │ 2902  │ GOOD    │
```

### 3.2 `series`

| Column | Type | Notes |
|---|---|---|
| `series_id` | `integer`, generated | Small number used in every reading row |
| `site`, `point_id` | `text`, **unique together** | The identity from the message |
| `unit` | `text`, nullable | QUDT ID, e.g. `DEG_C`; null for modes |
| `brick_class` | `text` | e.g. `brick:Zone_Air_Temperature_Sensor` |
| `kind` | `text`, `measurement` / `total` / `state` | From `dtteo:valueKind`; decides summaries |
| `first_seen`, `last_seen` | `timestamptz` | Handy for "which points are live?" without scanning readings (Tiger Data suggests this kind of column, link above) |

**Who fills it:** the historian, at start-up, from the asset model, using the same code as the gateway (`Mapper.points()`, step 2k). So the asset model stays the single source of truth; this table is a copy for joins and dashboards. If a message arrives for a point the historian doesn't know (the asset model changed without a restart), it goes to the quarantine table (3.4) with the reason. It is not dropped.

### 3.3 `readings` (hypertable)

A **hypertable** is TimescaleDB's name for a table that is automatically split into time **chunks** behind the scenes. You use it like a normal table; queries over a time range only touch the chunks they need.

| Column | Type | Notes |
|---|---|---|
| `series_id` | `integer`, references `series` | |
| `sensor_time` | `timestamptz` | Event time; the hypertable is split on this |
| `ingest_time` | `timestamptz` | Processing time |
| `value_num` | `double precision` | Numbers |
| `value_text` | `text` | Words (modes) |
| `value_bool` | `boolean` | On/off. This closes the gap noted in the review: ADR-001 only had number and text columns |
| `quality` | `text`: `GOOD` / `SUSPECT` / `BAD` | |
| `qc` | `jsonb`, nullable | The message's `qc` list as-is |
| `time_source` | `text`: `device` / `gateway` | |
| `source` | `text`, nullable | e.g. `tasmota:tasmota_zone1` |
| `msg_version` | `smallint` | The message `v` it came from (2), so a future v3 can be told apart |

Rules:
- **Exactly one value column is filled:** `CHECK (num_nonnulls(value_num, value_text, value_bool) = 1)`. `num_nonnulls` is a standard PostgreSQL function ([comparison functions](https://www.postgresql.org/docs/current/functions-comparison.html)).
- **Unique key `(series_id, sensor_time)`**, so a QoS 1 duplicate is skipped with `INSERT … ON CONFLICT DO NOTHING`. TimescaleDB requires that "UNIQUE and PRIMARY constraints must include the partitioning key" ([create_hypertable](https://www.tigerdata.com/docs/reference/timescaledb/hypertables/create_hypertable/)); ours does (`sensor_time`).
- **Created with `create_hypertable('readings', by_range('sensor_time'))`** on an ordinary table (the generalised API since TimescaleDB 2.13, same link). Not the newer `CREATE TABLE … WITH (tsdb.hypertable)`, because from 2.23 that switches on compression by default (`tsdb.columnstore` "defaults to true", [create_table](https://www.tigerdata.com/docs/reference/timescaledb/hypertables/create_table/)), and we want that to be a deliberate setting (section 7).
- Chunk size: TimescaleDB's default is fine at our volume (~0.5 GB a year, ADR-001 section 2).

```sql
-- sketch
CREATE TABLE readings (
  series_id   integer     NOT NULL REFERENCES series (series_id),
  sensor_time timestamptz NOT NULL,
  ingest_time timestamptz NOT NULL,
  value_num   double precision, value_text text, value_bool boolean,
  quality     text NOT NULL CHECK (quality IN ('GOOD','SUSPECT','BAD')),
  qc          jsonb,
  time_source text NOT NULL CHECK (time_source IN ('device','gateway')),
  source      text,
  msg_version smallint NOT NULL,
  CHECK (num_nonnulls(value_num, value_text, value_bool) = 1),
  UNIQUE (series_id, sensor_time)
);
SELECT create_hypertable('readings', by_range('sensor_time'));    -- the only TimescaleDB-specific line
```

**Known limit (from step 2i):** a reading with `time_source = 'gateway'` gets its arrival time, so a QoS 1 re-delivery has a different `sensor_time` and is stored twice. Accepted: devices we control send their own time, and these rows are marked.

### 3.4 `quarantine`

Every message on `dt/v1/quarantine/#`, plus anything the historian itself can't store. Columns mirror the quarantine message v2 (`site`, `stage`, `reason`, `topic`, `source`, `device`, `field`, `value` as `jsonb`, `raw`, `ingest_time`). A hypertable on `ingest_time`, so the production proposal's 90-day retention (ADR-001 section 9) is one policy, not a hand-written delete job. No unique key: an occasional duplicate in a debugging table is harmless.

### 3.5 Later tables (not built in stage 3)

`alerts`, `scenario_runs`, `twin_state`: ordinary tables, added by their own migrations when those services are built (ADR-001 decision item 4).

---

## 4. How the code reaches the database

The historian talks to storage through a small interface, as ADR-001 decided (VOLTTRON's "historian" pattern):

```python
class Historian(Protocol):
    def write(self, messages: list[dict]) -> None: ...     # canonical or quarantine messages
    def read(self, site: str, point: str, start, end) -> list[dict]: ...
```

`PostgresHistorian` is the one implementation now. Plain SQL through **psycopg 3** (no ORM, following the project's "scale before sophistication" principle).

---

## 5. Summaries, per kind of point

The summaries in `config/retention.yaml` (15 minutes and 1 hour) depend on the point's kind (step 2k; gauge vs counter as in [Prometheus metric types](https://prometheus.io/docs/concepts/metric_types)). BAD readings are left out of all summaries.

| Kind | Summary | How in v0.1 | Why this way |
|---|---|---|---|
| `measurement` | mean, min, max, count per bucket | **Continuous aggregates** `summary_15m`, `summary_1h` | A continuous aggregate is a summary table TimescaleDB keeps up to date by itself, on a schedule. Example shape: `CREATE MATERIALIZED VIEW … WITH (timescaledb.continuous) AS SELECT series_id, time_bucket('15 minutes', sensor_time) …` and `add_continuous_aggregate_policy(...)` ([create a continuous aggregate](https://tigerdata.com/docs/build/continuous-aggregates/create-a-continuous-aggregate)) |
| `total` (kWh) | energy used per bucket = sum of increases, allowing for meter resets | **A plain SQL view** using `LAG()` | Continuous aggregates don't allow window functions such as `LAG()` by default ("Window functions are disabled by default", same link). At our volume a view is fast enough. Upgrade path: TimescaleDB Toolkit's `counter_agg`, which ships in the TimescaleDB **HA** Docker image ([install Toolkit](https://www.tigerdata.com/docs/deploy/self-hosted/tooling/install-toolkit)) |
| `state` (mode) | time spent in each state per bucket | **A plain SQL view** using `LEAD()` | Same reason. Upgrade path: Toolkit's `state_agg` ([state_agg](https://docs.timescale.com/api/latest/hyperfunctions/state-tracking/state_agg)) |

Creating a continuous aggregate uses `WITH NO DATA`: "To create a continuous aggregate within a transaction block, use the WITH NO DATA option" (link above), and migrations run inside a transaction (section 6). The refresh policy then fills it.

The two views are standard SQL, so they also work on plain PostgreSQL (ADR-001's fallback). Only the continuous aggregates would need replacing.

---

## 6. Creating and changing the schema: numbered migrations

**The trap:** the PostgreSQL Docker image can run SQL files from `/docker-entrypoint-initdb.d`, but "Initialization scripts only run when the PostgreSQL data directory is empty" ([Docker: PostgreSQL initialization](https://docs.docker.com/guides/postgresql/advanced-configuration-and-initialization)). So a second change to the schema would never reach an existing database.

**The fix:** numbered **migration** files. Each file is one change, applied once, in order, and the database records which ones it has had. This is the standard way to evolve a schema.

**Tool: dbmate** (MIT licence, [pkg.go.dev](https://pkg.go.dev/github.com/amacneil/dbmate)), because:
- migrations are **plain SQL files** with `-- migrate:up` and `-- migrate:down` sections, so no ORM or Python framework is involved;
- it records applied files in a `schema_migrations` table and runs each one in a transaction;
- `dbmate wait` retries the connection until the database is up, which suits Docker Compose start-up;
- it ships as a Docker image (`ghcr.io/amacneil/dbmate`), so it runs as a one-off Compose service;
- it writes a `schema.sql` snapshot after each run, so the current schema is always readable in one file ([dbmate README](https://unpkg.com/dbmate@2.34.1/README.md)).

*Alternatives:* Alembic (Python, but built around SQLAlchemy); Flyway (Java); a hand-written runner (more code to own). dbmate is the smallest that does the job.

```
v0.1/storage/migrations/
  20261029120000_series_and_readings.sql      tables + create_hypertable
  20261029120100_quarantine.sql
  20261029120200_roles.sql                    section 8
  20261029120300_summaries.sql                continuous aggregates + views
  20261029120400_policies.sql                 refresh, and retention/compression from config/retention.yaml
```

Timescale-specific lines are kept in clearly named files, so the plain-PostgreSQL fallback means swapping those files only.

---

## 7. Writing: the historian

```
broker ──(dt/v1/telemetry/#, dt/v1/quarantine/#, QoS 1, persistent MQTT 5 session)──► historian
historian: buffer ─► every 1 s or 500 messages ─► one transaction: INSERT … ON CONFLICT DO NOTHING
                                                 ─► COMMIT ─► acknowledge those messages to the broker
```

**7.1 Acknowledge only after the data is saved.** By default paho "acknowledges messages as soon as they are delivered to the caller". With `manual_ack_set(True)`, "the caller MUST manually acknowledge every message once application processing is complete using ack()" (paho-mqtt 2.1.0 source, `Client.manual_ack_set` and `Client.ack`). The historian acks only after `COMMIT`. If it crashes before that, the broker re-delivers the messages, and the unique key skips any already saved. So: **at least once delivery + duplicate-proof writes = each reading stored once** (except gateway-stamped ones, 3.3). Acks are sent in the order messages arrived, as MQTT requires ("It MUST send PUBACK packets in the order in which the corresponding PUBLISH packets were received", quoted in [HiveMQ, message ordering](https://www.hivemq.com/blog/understanding-mqtt-message-ordering/)).

**7.2 Back-pressure for free.** With MQTT 5, a client tells the broker its **Receive Maximum**: the most un-acknowledged QoS 1 messages it will take at once ([HiveMQ](https://www.hivemq.com/blog/understanding-mqtt-message-ordering/)). If the database is down, the historian stops acking, the broker stops sending at that limit and holds the rest (persistently, step 2j). The historian's memory can't run away. *To check in the build:* Mosquitto 2.0.22's handling of Receive Maximum (2.1.0's release notes say it "now enforces" it for MQTT v5 clients, [2.1.0 notes](https://mosquitto.org/blog/2026/01/version-2-1-0-released/)).

**7.3 Batched inserts.** One transaction per batch, with psycopg 3's `executemany()`, which "makes use internally of the pipeline mode", sending many statements in few network round trips ([psycopg pipeline mode](https://psycopg.org/psycopg3/docs/advanced/pipeline.html)). One commit per second instead of per row.

**7.4 Session.** Client ID `historian`, `clean_start=False`, session expiry 7 days, like the gateway (step 2j). Later, several historians can share the load with `$share/historians/dt/v1/telemetry/#` (`contracts/topics.md`).

---

## 8. Who can do what (database roles)

| Role | Can | Used by |
|---|---|---|
| `dtteo_owner` | Create and change tables | dbmate (migrations) only |
| `historian_writer` | `INSERT`/`SELECT` on `readings`, `quarantine`; `INSERT`/`UPDATE` on `series` | The historian |
| `grafana_reader` | `SELECT` only | Grafana, and read-only tools such as the ML workstation's exports |

Grafana's own documentation says the database user "should have only SELECT permissions on the relevant schemas and tables", because "Grafana does not validate the safety of queries, so users could run potentially harmful SQL (for example, DROP TABLE)" ([Grafana PostgreSQL data source](https://grafana.com/docs/grafana/latest/datasources/postgres/configure/)). Passwords live in a `.env` file that is **not** committed (`.gitignore`), read by Docker Compose.

The database port stays inside the Compose network (README section 6). To use a desktop tool (pgAdmin, DBeaver) on the lab PC, publish it on the PC only: `127.0.0.1:5432:5432`, never `5432:5432`.

---

## 9. Backups

The data is grant evidence, so it's backed up from day one.

- **How:** `pg_dump -Fc` (PostgreSQL's custom-format dump), run on demand with `docker compose run --rm backup` (before any migration, and regularly once there's real data; schedule it then). File name includes the date, the PostgreSQL version and the TimescaleDB version, because Timescale's docs say to "keep track of the versions of PostgreSQL and TimescaleDB you are running" ([logical backup](https://www.tigerdata.com/docs/deploy/self-hosted/backup-and-restore/logical-backup)).
- **Restore** (same link): create the database and extension → `SELECT timescaledb_pre_restore();` → `pg_restore -Fc` → `SELECT timescaledb_post_restore();`. Not `pg_restore -j`: "This option does not correctly restore the TimescaleDB catalogs."
- **Test the restore** once in the build step, into a throwaway database. A backup that's never been restored isn't known to work.
- **Where:** `v0.1/backups/` on the lab PC (git-ignored). **No off-PC copy yet:** there is no backup device or site, and little data. Add one before real site data arrives. The **live database files stay in a Docker named volume**, not in a folder inside OneDrive: a sync tool copying files of a running database can capture them half-written, whereas a Docker volume is a persistent data store "created and managed by Docker" ([Docker volumes](https://docs.docker.com/engine/storage/volumes/)), outside the synced folder.

---

## 10. Bulk history (CSV back-fill)

README section 4 already sets the rule: bulk history goes through the same checks but skips the twin. That's the common **hot path / cold path** split, where live data is processed immediately and history in batches ([Atmosera, Azure IoT reference architecture](https://www.atmosera.com/blog/an-azure-iot-reference-architecture-for-azure/)).

**Proposal:** a CSV importer that runs the gateway's `Pipeline` **in the same process** (it has no MQTT inside it, by design, step 2h) with the late-arrival check off (`max_age=None`), then writes through the same `Historian.write()`. Not through the broker, so a year of history doesn't flood the twin and alerts with old data. Same decode → map → normalise → validate, same contract, same table, `source` = `csv:<file name>`.

---

## 11. Retention and compression

Read from `config/retention.yaml` by the policies migration (section 6).

| Setting | Feasibility (active) | Production (proposal) |
|---|---|---|
| Raw readings | Keep all: no retention policy created | 2 years |
| Summaries | Keep all | Contract length |
| Quarantine | Keep all | 90 days |
| **Compression** | **Off.** ~0.5 GB a year doesn't need it, and late or back-filled rows are simplest to write into uncompressed chunks | On for chunks older than a few weeks; settings tested before pilot |

ADR-001 section 9's rule still holds: raw data is deleted only after its summaries exist.

---

## 12. Prototype vs production

| | Feasibility (this ADR) | Production (later) |
|---|---|---|
| Database | One container, `timescale/timescaledb:2.31.0-pg18` (exact version pinned; not the `-oss` tags, which lack the Community features ADR-001 relies on) | Managed PostgreSQL or Tiger Cloud; licence reviewed first (ADR-001) |
| Historian | One instance | Several, with a shared subscription |
| Summaries | Continuous aggregates + SQL views | Toolkit `counter_agg` / `state_agg` if views get slow |
| Backups | On-demand `pg_dump` to a local folder | Point-in-time recovery from the managed service |
| Customers | One test site | `site` per customer site; separate databases or row-level security per customer, decided then |

---

## 13. Consequences

| | |
|---|---|
| **Good** | One reading = one row, identified by `site` + `point` + time; duplicates skipped; reasons stored; correct summaries for kWh and modes; schema changes are repeatable; nothing lost if the database is down; restore is written down |
| **Cost** | Two more containers (database, one-off dbmate) and one service (historian) |
| **Risk** | Gateway-stamped readings can be stored twice (accepted, marked). Receive Maximum behaviour on Mosquitto 2.0 to be confirmed in the build |
| **Portability** | Only `create_hypertable`, the continuous aggregates and the policies are TimescaleDB-specific, all in named migration files |

---

## 14. Open questions

1. ~~Confirm the layout~~ Confirmed 29 Oct 2026.
2. ~~PostgreSQL 17 or 18~~ **18** (29 Oct 2026).
3. Off-PC backup location: **not needed yet** (no backup device or site; little data). Revisit before real site data.

---

## Change log

| Date | Change |
|---|---|
| 2026-10-28 | Proposed |
| 2026-10-29 | Accepted: PostgreSQL 18; backups local only for now. Built in stage 3a (`storage/NOTES.md`); summaries (section 5) come once the historian is storing data |
