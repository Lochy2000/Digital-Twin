# ADR-001: Where readings are stored (time-series store)

**Status:** Accepted, 19 October 2026, for the feasibility study (v0.1). Proposed the same day.

**Licence position:** this is a feasibility-scale prototype. TimescaleDB Community (TSL) is accepted for it without a formal licence review. The licence will be reviewed **before any commercial or pilot deployment**, and dealt with then: either confirm the TSL is fine for the product, or move to plain PostgreSQL (option A), which the design already allows.

*An ADR (Architecture Decision Record) is a short note of one decision: the context, the options, what was chosen and the consequences. The UK Government's [GDS Way](https://gds-way.digital.cabinet-office.gov.uk/standards/architecture-decisions.html) recommends them and suggests keeping them in version control. Later decisions go in this folder as ADR-002, ADR-003 and so on.*

---

## 1. The question

Stage 3 needs a database that stores every canonical message the gateway publishes, plus the things the later stages produce (twin state, residuals, alerts, scenario runs). Which one?

The existing root prototype uses **InfluxDB 2.7**. The v0.1 README proposed **TimescaleDB**. Neither has been checked against our actual requirements, which is what this record does.

---

## 2. Requirements

Each requirement comes from a project document or from what the gateway already does.

| # | Requirement | From |
|---|---|---|
| R1 | Store raw telemetry, model outputs and residuals; fast time-range and downsampled ("average per hour") queries | Feasibility reference, tier 4 (Persistence) |
| R2 | **Long-range queries** (weeks or months) for calibration: "fit on one period, evaluate on a held-out period" | Feasibility reference, section 6.3; WP5 training data |
| R3 | Store **numbers and words**: e.g. `unit1.mode_status = "cool"` | Canonical message: `value` is number, text or true/false |
| R4 | Keep **two times** per reading, and accept **late, out-of-order or replayed** data | Canonical message; feasibility "delayed arrival" tests |
| R5 | **Ignore duplicates**: MQTT QoS 1 can deliver a message twice; keep one row per point + `sensor_time` | `contracts/topics.md` |
| R6 | Also hold **non-time-series data**: alerts, scenario-run records, twin state | README, container view (D-02) |
| R7 | **Low cost**: prototype "low tens of pounds per month"; production cost "dominated by storage and support" | Feasibility reference, prototype vs production |
| R8 | **Single host now**, managed and scalable later; separate customers' data in production | Feasibility reference, prototype vs production |
| R9 | **Open licence, commercial use allowed, no lock-in** | v0.1 design principles |
| R10 | Works with **Grafana** for engineering dashboards | README, container view |
| R11 | **Retention and lifecycle**: delete or thin old data on a policy; data can be exported | RR outline 6.7 (ownership) and 6.8 (retention) |

### How much data, roughly?

This is an estimate, assuming one row per reading and plain PostgreSQL row overheads (a 23-byte row header and a 4-byte pointer per row, from the [PostgreSQL page layout docs](https://access.crunchydata.com/documentation/postgresql11/11.4/storage-page-layout.html)). That works out at about 88 bytes per row including the index, with no compression.

| Case | Points × interval | Rows per second | Rows per year | Size per year |
|---|---|---|---|---|
| Feasibility rig | 10 × 60 s | 0.2 | 5 million | ~0.5 GB |
| Small SME site | 30 × 30 s | 1 | 32 million | ~3 GB |
| Dense site | 100 × 10 s | 10 | 315 million | ~28 GB |

**What this means:** even a dense site writes about **10 rows a second**. ThingsBoard, a widely used open-source IoT platform, says plain PostgreSQL handles **5,000 to 10,000 data points per second** and only suggests switching database above that ([ThingsBoard database docs](https://thingsboard.io/docs/reference/architecture/database/)). **Write speed is not what decides this.** The decision rests on R2 (long queries), R3 to R6 (data shape) and R9 (licence).

---

## 3. What similar platforms do

| Platform | What it stores time series in | Lesson for us |
|---|---|---|
| **ThingsBoard** (IoT platform) | PostgreSQL by default; adds Cassandra only above 5–10K points/s. Values can be text, true/false, whole numbers, decimals or JSON. | Plain PostgreSQL is a normal starting point; mixed value types are normal ([docs](https://thingsboard.io/docs/reference/architecture/database/), [telemetry](https://thingsboard.io/docs/user-guide/telemetry/)) |
| **FIWARE QuantumLeap** (EU smart-city / digital-twin history service) | CrateDB by default, or **Timescale** (PostgreSQL + Timescale + PostGIS) | TimescaleDB is an established backend for twin history ([docs](https://quantumleap.readthedocs.io/)) |
| **VOLTTRON** (PNNL building and energy platform) | Pluggable "historians": SQL (SQLite, MySQL, PostgreSQL, with an optional TimescaleDB hypertable), MongoDB, Crate, InfluxDB | Storage behind an interface, so the backend can change: the same approach we've taken ([historians](https://volttron.readthedocs.io/en/stable/agent-framework/historian-agents/historian-framework.html), [SQL historian](https://volttron.readthedocs.io/en/main/agent-framework/historian-agents/sql-historian/sql-historian.html)) |
| **Azure Digital Twins** | Azure Data Explorer. One narrow table: twin ID, property, value, plus **two times** (processing time and "when the update was observed in the real world") | Same shape as our canonical message: narrow rows, two timestamps ([data history](https://learn.microsoft.com/azure/digital-twins/concepts-data-history)) |
| **Eclipse Ditto** (open-source twin framework) | Its own history API, which it says is "not comparable with the features of a time series database" | Twin frameworks keep a separate time-series store ([history](https://eclipse.dev/ditto/3.3/basic-history.html)) |
| **AWS Timestream for LiveAnalytics** | Closed to new customers on 20 June 2025; AWS now points them to Timestream for InfluxDB | A managed, proprietary store can disappear: R9 matters ([notice](https://docs.aws.amazon.com/timestream/latest/developerguide/AmazonTimestreamForLiveAnalytics-availability-change.html)) |
| **FENECON / OpenEMS** (energy management) | InfluxDB, per an InfluxData customer story (vendor page, so weak evidence) | InfluxDB is common in energy monitoring ([story](https://www.influxdata.com/customer/fenecon/)) |

**About benchmarks:** most published speed comparisons are run by one of the vendors (TimescaleDB, QuestDB, InfluxData), so they aren't used here. At about 10 rows a second they wouldn't change the answer anyway.

---

## 4. The options

### A. Plain PostgreSQL
A general-purpose open-source database. Tables can be split by time ("partitioning"), and `INSERT … ON CONFLICT DO NOTHING` ignores duplicates.
- **Good:** fully open (PostgreSQL licence); widely offered as a managed cloud service; holds alerts and runs in the same database; built into Grafana ([Grafana data sources](https://grafana.com/docs/grafana/v13.2/datasources.md)).
- **Weak:** no built-in compression, automatic downsampling or retention policies. These would have to be written and scheduled by us.

### B. TimescaleDB (PostgreSQL extension) — *proposed*
Adds time-series features to PostgreSQL. A normal table becomes a "hypertable", split into time chunks automatically. Two editions ([editions page](https://www.tigerdata.com/docs/get-started/choose-your-path/timescaledb-editions)):
- **Apache 2 edition:** hypertables only.
- **Community edition** (Tiger Data / Timescale License, "TSL"): adds compression (columnstore), continuous aggregates (automatic hourly/daily averages), retention policies and background jobs. Free to use and modify; the restriction, in the vendor's words: "you cannot make modifications to the TimescaleDB Community Edition source code and offer it as a service".

**Good:**
- Everything plain PostgreSQL has: SQL, one database for alerts and runs too, Grafana.
- The time-series features R1, R2 and R11 need.
- Duplicates are skipped with `ON CONFLICT DO NOTHING`, as long as the unique key includes the time column, which ours does: point + `sensor_time` ([upsert docs](https://www.tigerdata.com/docs/build/data-management/write-data/upsert), [unique indexes](https://www.tigerdata.com/docs/use-timescale/latest/hypertables/hypertables-and-unique-indexes)).

**Weak:**
- The useful features are under the TSL, which is source-available, not open source. Botanic should confirm it's acceptable.
- Single node.

### C. InfluxDB 3 Core
InfluxData's current open-source line (MIT / Apache 2), with SQL and InfluxQL.
- **Good:** purpose-built for time series; open licence; built into Grafana; managed versions exist (InfluxData, AWS Timestream for InfluxDB).
- **Weak, and decisive for R2:**
  - InfluxData describes Core as a "recent-data engine". A single query may read at most 432 files by default, which is "up to 72 hours of data" ([config docs](https://docs.influxdata.com/influxdb3/core/reference/config-options/index.md), [InfluxData blog](https://www.influxdata.com/blog/influxdb3-open-source-public-alpha-jan-27/)).
  - Long-range querying needs the compactor in **InfluxDB 3 Enterprise**, which needs a commercial licence for Botanic.
  - Core has limits of 5 databases and 2,000 tables ([database docs](https://docs.influxdata.com/influxdb3/core/admin/databases/)).
  - Alerts and runs would need a second database.

### D. InfluxDB 2.x (what the root prototype uses)
- **Good:** already running; Grafana support.
- **Weak:** the legacy line. Its query language Flux "is in maintenance mode and is not supported in InfluxDB 3" ([Flux status](https://docs.influxdata.com/flux/v0/future-of-flux)), so anything built on it must be rewritten to move forward. It also has the same second-database problem as C.

### E. QuestDB
An open-source time-series database (Apache 2) that speaks the PostgreSQL wire protocol.
- **Good:** fast; handles out-of-order data; built-in de-duplication (`DEDUP UPSERT KEYS`) ([site](https://questdb.com/), [dedup](https://questdb.com/blog/solving-duplicate-data-performant-deduplication/)).
- **Weak:**
  - High availability, replication and access control are Enterprise features.
  - A smaller ecosystem.
  - Alerts and runs would most likely still want PostgreSQL alongside.
  - This is the credible runner-up if TSL is rejected *and* plain PostgreSQL proves too slow, which the volume estimate says is unlikely.

### Later, in the cloud
Not a choice for v0.1, but it shows the route stays open:
- Option A is widely available as a managed cloud service.
- Option B runs on its vendor's cloud (Tiger Cloud), or self-hosted on any VM.
- Azure Data Explorer is what Azure Digital Twins itself uses.

---

## 5. Requirements vs options

✔ meets · ◐ partly / with work · ✘ does not

| | A. PostgreSQL | **B. TimescaleDB** | C. InfluxDB 3 Core | D. InfluxDB 2.x | E. QuestDB |
|---|---|---|---|---|---|
| R1 time-range + downsampled queries | ◐ we write it | ✔ continuous aggregates | ✔ | ✔ | ✔ |
| R2 long-range queries (weeks) | ✔ | ✔ | ✘ ~72 h per query by default | ✔ | ✔ |
| R3 numbers and words | ✔ | ✔ | ✔ | ✔ | ✔ |
| R4 two times, late data | ✔ | ✔ | ✔ | ✔ | ✔ |
| R5 ignore duplicates | ✔ `ON CONFLICT` | ✔ `ON CONFLICT` | ◐ last write wins* | ◐ last write wins* | ✔ `DEDUP` |
| R6 alerts, runs in same DB | ✔ | ✔ | ✘ second DB | ✘ second DB | ◐ |
| R7 low cost | ✔ | ✔ | ✔ | ✔ | ✔ |
| R8 single host now, managed later | ✔ widely managed | ✔ / ◐ vendor cloud | ✔ / ◐ Enterprise | ◐ legacy | ✔ / ◐ Enterprise |
| R9 open, no lock-in | ✔ | ◐ TSL for key features | ✔ Core / ✘ Enterprise | ◐ Flux dead end | ✔ |
| R10 Grafana | ✔ built in | ✔ built in | ✔ built in | ✔ built in | ◐ plugin ([QuestDB plugin](https://grafana.com/grafana/plugins/questdb-questdb-datasource/)) |
| R11 retention, export | ◐ we write it | ✔ policies | ✔ | ✔ | ✔ |

*"Last write wins" (R5): InfluxDB treats points with the same measurement, tags and timestamp as one point, and "uses the field value of the new point" ([InfluxDB v2 duplicate points](https://docs.influxdata.com/influxdb/v2/write-data/best-practices/duplicate-points/index.md)). So a QoS 1 duplicate doesn't create a second row. That's acceptable, but less explicit than a unique key; InfluxDB 3 not re-checked.*

---

## 6. Decision

**Use PostgreSQL with the TimescaleDB extension (Community edition) for v0.1, written so that it still runs on plain PostgreSQL.**

In practice:
1. *(Refined by [ADR-002](ADR-002-database-layout.md), proposed 28 Oct 2026: a small `series` table holds each site + point once, the readings table references it, the unique key is `series_id` + `sensor_time`, and a true/false value column is added.)* **One table, one row per reading:** point, `sensor_time`, `ingest_time`, a numeric value column and a text value column, unit, quality, source. Unique key: point + `sensor_time`, so QoS 1 duplicates are skipped with `ON CONFLICT DO NOTHING`.
2. **Standard SQL in the code.** TimescaleDB features (hypertable, compression, hourly averages, retention) are switched on by a setup script, not used inside the application code. If the licence is rejected, the same code runs on plain PostgreSQL (option A), and only those housekeeping features need replacing.
3. **The historian sits behind a small interface** (`write(messages)`, `read(point, from, to)`), as VOLTTRON does. Swapping to QuestDB or a cloud store later means one new class.
4. **Alerts, scenario runs and twin state** go in ordinary tables in the same database.

**Why:**
- It's the only option that meets every requirement without a second database or a paid licence: R2 rules out InfluxDB 3 Core, and R6 counts against all the Influx options.
- It matches the precedents (FIWARE QuantumLeap, VOLTTRON, ThingsBoard's PostgreSQL default).
- Its fallback is ordinary PostgreSQL, which is the lowest-risk choice there is.

---

## 7. Consequences and risks

| | |
|---|---|
| **Good** | One database, SQL that any engineer or ML tool can read, long-range queries for calibration, a clear fallback |
| **Licence** | Compression, continuous aggregates and retention policies are under the TSL. Accepted for the feasibility prototype; **to be reviewed before commercial or pilot use** (a legal check, not a technical one). The vendor's summary is that you can run and modify it yourself but not offer it as a service; Botanic would be selling a twin product that uses it, not the database. |
| **Migration** | The root prototype's InfluxDB 2.7 data and Flux queries don't carry over. They're test data, so this is low cost. |
| **Scale** | Single node. Fine by a wide margin at the estimated volumes. Revisit when sites × points × rate exceeds a few thousand rows per second. |
| **Vendor** | The company behind TimescaleDB renamed itself Tiger Data and controls the TSL. A future licence change is possible; the plain-PostgreSQL fallback covers it. |

---

## 8. Open questions for Botanic

1. ~~Is the TSL acceptable?~~ **Settled for now (19 Oct 2026):** accepted for the feasibility study; to be reviewed before commercial or pilot deployment. If rejected then: plain PostgreSQL (option A).
2. ~~How long must raw readings be kept?~~ **Set for now (19 Oct 2026):** see section 9. Feasibility keeps everything; the production periods are a proposal to confirm with Botanic before any pilot.
3. Any customer requirement on **where** data is stored (UK only)? This affects the cloud choice later, not the database.

---

## 9. Retention (how long data is kept)

> **⚠ REVIEW BEFORE PILOT OR COMMERCIAL USE.** Set 19 October 2026 for the feasibility study. The feasibility values are deliberate; the production values are a **proposal** based on the reasoning below, not on a customer or legal requirement. The settings file the storage setup reads is [`config/retention.yaml`](../config/retention.yaml); change the values there and update this section.

**Why these numbers.** No standard sets a retention period for building telemetry, so it follows what the data is used for:
- **Calibration and savings need at least a full year.** IPMVP says the baseline should "span a full operating cycle from maximum energy consumption and demand to minimum" and "is often a year" ([IPMVP principles](https://evo-world.org/images/corporate_documents/IPMVP-Generally-Accepted-Principles_Final_26OCT2018.pdf)).
- **Tiered retention is the common pattern:** detail for a while, summaries for good. Home Assistant keeps detail for 10 days and hourly statistics "never deleted automatically" ([docs](https://www.home-assistant.io/docs/configuration/long-term-statistics/)). TimescaleDB's own example keeps raw data 30 days and daily summaries 600 days ([docs](https://www.tigerdata.com/docs/learn/data-lifecycle/data-retention/data-retention-with-continuous-aggregates)). ThingsBoard keeps everything by default ([docs](https://thingsboard.io/docs/pe/recipes/configure-telemetry-ttl/)).
- **Cost isn't the limit at this scale:** roughly 0.5 to 3 GB of raw readings per site per year (section 2).
- **Personal data has no fixed limit, but "you cannot keep it for longer than you actually need it"** ([ICO](https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/data-protection-principles/a-guide-to-the-data-protection-principles/storage-limitation/)). The feasibility study uses simple sensor readings (temperatures, power, modes) that don't identify people.
- **ESOS** (UK energy audits) only covers large undertakings, which most SME customers aren't ([NetRegs](https://www.netregs.org.uk/environmental-topics/carbon-reduction-and-efficiency/energy-saving-opportunities-scheme-esos/)). A customer that is covered gets an export rather than us keeping data indefinitely.

| Data | **Feasibility (active now)** | Production (proposal, not active) |
|---|---|---|
| Raw readings (every canonical message) | Keep all | 2 years rolling |
| 15-minute and hourly summaries (mean, min, max) | Built; keep all | Length of customer contract (placeholder: 10 years) |
| Alerts, scenario runs | Keep all | Length of customer contract |
| Quarantine messages | Keep all | 90 days |
| End of a customer contract | n/a | Export to the customer, then delete (contract decides) |

**Rules that go with it:**
1. **Raw data is only deleted once its summaries exist.** TimescaleDB warns that deleting raw data inside an aggregate's refresh window also removes the aggregated values (link above).
2. **Sensors that could identify people** (occupancy, motion, CO₂ in small rooms) are **out of scope for feasibility**. If added later, they get their own shorter retention, or are stored as summaries only, and this section must be reviewed first.
3. **Any change** to these values: edit `config/retention.yaml`, update this table, and note the date and reason below.

**Change log**

| Date | Change | Why |
|---|---|---|
| 2026-10-19 | First version: feasibility keeps everything; production proposal as above | Feasibility uses simple sensor data at small volume; production values to confirm with Botanic |

