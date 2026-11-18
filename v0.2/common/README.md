# dtteo-common

Code and contracts that **both** the gateway (Pi) and the platform (server) use, so each
exists once. Installed as a Python package by each service.

| Module | What it is |
|---|---|
| `dtteo_common.mapper` | Reads the asset model + mappings (Turtle) into a lookup table. Gateway: maps readings. Historian: lists the points for the database |
| `dtteo_common.units` | Unit conversions (QUDT names) |
| `dtteo_common.modbus_types` | Modbus data types and register counts |
| `dtteo_common.logfmt` | `kv()`: one `key=value` log line per event |
| `dtteo_common.contracts` | The message JSON Schemas (folder `contracts/`, with notes, examples and `topics.md`) |

**Install for development** (from `gateway/` or `platform/historian/`):

```
pip install -e ../common          # gateway        (../../common from platform/historian)
```

`-e` (editable) means edits here show up immediately, no reinstall.

**Tests:** `cd common && python -m pytest -q`, and `cd contracts && python check_examples.py`.

**After the repo split** each service installs a fixed version instead:
`pip install "git+<repo url>@<tag>#subdirectory=common"`. Change the contracts → bump `version`
in `pyproject.toml` → update both services. The message's own `"v"` field catches a mismatch.
