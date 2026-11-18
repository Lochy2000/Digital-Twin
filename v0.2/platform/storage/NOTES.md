# storage/: developer notes

Design and reasons: `decisions/ADR-002-database-layout.md`. These notes record what was built.

---

## 2026-10-29 · Stage 3a: the database

### What's here

| File | Does |
|---|---|
| `migrations/*.sql` | The schema, one change per file, applied in order by **dbmate** (the `migrate` service). Each has `-- migrate:up` and `-- migrate:down` |
| `init/10_users.sh` | Creates the `historian` and `grafana` logins from `.env`. Runs once, on the database's first start |
| `backup.sh` | One `pg_dump` into `v0.1/backups/` (`docker compose run --rm backup`) |

| Migration | Creates | TimescaleDB? |
|---|---|---|
| `..120000_series_and_readings` | `series`, `readings` | No |
| `..120100_quarantine` | `quarantine` | No |
| `..120200_timescale_hypertables` | Makes `readings` and `quarantine` hypertables | **Yes** |
| `..120300_roles_and_grants` | `dtteo_writer` (historian), `dtteo_reader` (Grafana, SELECT only) | No |
| `..140000_summary_views` | `total_15m`, `total_1h`, `state_spans` (stage 3c) | No |
| `..140100_summaries_timescale` | `summary_15m`, `summary_1h` (stage 3c) | **Yes** |

### First run (Windows, from `v0.1`)

```bat
copy .env.example .env          :: then edit the three passwords (letters and digits)
docker compose up -d
docker compose logs migrate     :: expect one "Applied: ..." per migration file (6 after stage 3c)
docker compose exec timescaledb psql -U dtteo_owner -d dtteo -c "\dt"
```

Every `docker compose` command now needs `.env` to exist; it stops with "copy .env.example to .env" if not.

### Adding a change later

Add a new file to `migrations/` with a later timestamp in its name (`YYYYMMDDHHMMSS_what.sql`) and run `docker compose up migrate`. **Never edit a migration that has already been applied**; dbmate only runs each file once.

### Restore a backup

From the TimescaleDB docs ([logical backup](https://www.tigerdata.com/docs/deploy/self-hosted/backup-and-restore/logical-backup)); needs the same PostgreSQL/TimescaleDB versions (they're in the file name):

```bat
docker compose exec timescaledb psql -U dtteo_owner -d postgres -c "CREATE DATABASE dtteo_restore"
docker compose exec timescaledb psql -U dtteo_owner -d dtteo_restore -c "CREATE EXTENSION timescaledb; SELECT timescaledb_pre_restore();"
docker compose cp backups\<file>.dump timescaledb:/tmp/restore.dump
docker compose exec timescaledb pg_restore -U dtteo_owner -d dtteo_restore /tmp/restore.dump
docker compose exec timescaledb psql -U dtteo_owner -d dtteo_restore -c "SELECT timescaledb_post_restore();"
```

Not `pg_restore -j` (the docs say it "does not correctly restore the TimescaleDB catalogs").

### Things to know

- **Data lives in the `timescale-data` Docker volume**, not in this folder (live database files must not sit in OneDrive). `docker compose down -v` deletes it.
- **The TimescaleDB image's own first-start scripts still run.** Only our one file is mounted into `/docker-entrypoint-initdb.d`, not the whole folder, which would hide the image's `000_install_timescaledb.sh` and `001_timescaledb_tune.sh`.
- `*.sh` files keep Unix line endings (`v0.1/.gitattributes`); a Windows line ending breaks them inside the container.
- Telemetry to the vendor is off (`TIMESCALEDB_TELEMETRY: "off"`).

### Checked

Docker Hub isn't reachable from the build environment, so TimescaleDB itself couldn't be run there. Checked on PostgreSQL 16 with dbmate 2.37.0, everything except the TimescaleDB file:
- the first-start script creates the users; all migrations apply; a second run applies nothing; all roll back and re-apply;
- `historian` can add series and readings, a duplicate (same series + time) is skipped, two value columns at once is refused, it can't delete;
- `grafana` can read (including tables added later) but can't insert or drop;
- `backup.sh` writes a dump that `pg_restore -l` can read.

**Still to check on your PC:** the first `docker compose up -d` (the TimescaleDB migration and the image's own scripts).

### Next: stage 3b, the historian

Subscribes to the canonical and quarantine topics and writes them here (ADR-002 section 7).

---

## 2026-10-29 · Stage 3c: summaries and a first Grafana dashboard

### Summaries (ADR-002 section 5)

| Name | Kind of point | Gives | How |
|---|---|---|---|
| `summary_15m`, `summary_1h` | measurement | mean, min, max, count per bucket | TimescaleDB continuous aggregates (`..140100_summaries_timescale.sql`). Re-summarise the last 7 days on a schedule; "real-time" mode adds the newest readings when queried |
| `total_15m`, `total_1h` | total (kWh) | how much it went up per bucket | Plain view (`..140000_summary_views.sql`). A drop counts as a meter reset, as Prometheus does |
| `state_spans` | state (mode) | each state with its start and end time | Plain view |

BAD readings are left out of all of them. Readings older than 7 days that arrive late (a CSV back-fill) need one manual refresh: `CALL refresh_continuous_aggregate('summary_1h', '<from>', '<to>');`

### Grafana

`http://localhost:3000`, user `admin`, password `GRAFANA_ADMIN_PASSWORD` from `.env` (add that line to your existing `.env`; without it the password is `admin` and Grafana asks you to change it). Only reachable from this PC.

- The database connection and the **DT-TEO overview** dashboard are created automatically from `grafana/` (Grafana "provisioning").
- Panels: measurements (every reading, and hourly mean), energy used per hour, mode timeline, readings by quality, latest quarantine. "Measurement points" at the top chooses what's plotted.
- Grafana logs in as `grafana` (SELECT only).
- The JSON file is the master copy: changes made in Grafana can't be saved over it. To keep one, export the dashboard JSON over `grafana/dashboards/dtteo-overview.json`.

### Checked

On PostgreSQL 16: the views apply and roll back; a meter going 100.0 → 101.0, then reset to 0.2 → 0.7, gives **1.0 kWh** then **0.7 kWh** per hour; mode spans are right; BAD readings are left out; every dashboard query (except the hourly mean, which needs TimescaleDB) runs as the `grafana` login.

**Still to check on your PC** (TimescaleDB and Grafana images couldn't be pulled in the build environment): the continuous-aggregate migration, and that Grafana loads the dashboard.

---

## 2026-10-31 · Quick fixes after the first full run

- **Dashboard:** "Readings by quality" shows GOOD / SUSPECT / BAD as three labelled numbers (Grafana's default colour rule had turned any count over 80 red). "Hourly mean" includes any hourly bucket that overlaps the time range (buckets are stamped at the start of the hour). Mode colours: heat orange, cool blue, off grey.
- **Smoke test:** `python tools\smoke_test.py` (from `v0.1`, stack running) checks migrations, the reading path, the quarantine path, the summaries and Grafana, then deletes its test rows. First run on the lab PC, 31 Oct 2026: all 6 checks passed.
- Grafana is pinned to 13.2.5 (changed from 13.2.6 on the lab PC).
