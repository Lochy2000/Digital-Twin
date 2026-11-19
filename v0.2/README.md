# DT-TEO v0.2

v0.1 split into the parts that will become separate repos. Design and evidence for the
pipeline itself stay in [`../v0.1`](../v0.1) (README, ADRs, FINDINGS).

| Folder | Becomes | Runs on | What |
|---|---|---|---|
| `common/` | `dtteo-common` package | (installed by both) | Mapper, units, log format, message contracts |
| `gateway/` | `dt-gateway` repo | Pi 5 | Broker + ingestion gateway |
| `platform/` | `dt-platform` repo | Server | Database, historian, Grafana, backups |
| `dev/` | stays here | Laptop | Runs everything together + fake test vendors + smoke test |

## Run it all on the laptop

```
cd dev
copy .env.example .env          # then change the passwords
docker compose --profile acme up -d --build
python smoke_test.py            # 9 checks, about 15 s
```

Grafana: http://localhost:3000. Stop: `docker compose down` (`down -v` also deletes the data).

## Tests (no Docker needed)

```
python -m venv .venv ; .venv\Scripts\Activate.ps1
pip install -e common
pip install -r gateway\requirements-dev.txt -r platform\historian\requirements-dev.txt
cd common ; python -m pytest -q ; cd ..\gateway ; python -m pytest -q ; cd ..\platform\historian ; python -m pytest -q
```

## Replay a rig recording (dt-edge readings.csv)

```
python dev\replay_run.py path\to\readings.csv [more parts.csv]              # offline summary, no Docker
python dev\replay_run.py path\to\readings.csv --publish                     # into the dev stack
```

Changes and the reasons for them: [`CHANGELOG.md`](CHANGELOG.md).
