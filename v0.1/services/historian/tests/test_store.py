"""
Store tests. The first group needs no database. The second group needs a PostgreSQL database
with storage/migrations applied, given as TEST_DATABASE_URL (as its owner, e.g.
postgresql://dtteo_owner:pw@127.0.0.1:5432/dtteo); otherwise those tests are skipped.
WARNING: the database tests empty the readings, quarantine and series tables first.
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from gateway.mapper import Mapper
from historian.service import contract_validator
from historian.store import Message, PostgresHistorian, StoreUnavailable, Unstorable, value_columns

V01 = Path(__file__).resolve().parents[3]
DB = os.getenv("TEST_DATABASE_URL")
needs_db = pytest.mark.skipif(not DB, reason="set TEST_DATABASE_URL to run database tests")


def canonical(point="unit1.zone_air_temp", value=21.4, t="2026-10-29T10:00:00.000Z", **extra):
    m = {"v": 2, "site": "site1", "point": point, "value": value, "unit": "DEG_C",
         "sensor_time": t, "ingest_time": t, "time_source": "device", "quality": "GOOD",
         "source": "test:dev1"}
    m.update(extra)
    return Message("dt/v1/telemetry/site1/" + point.replace(".", "/"), json.dumps(m).encode())


# --- No database needed --------------------------------------------------------------------

def test_true_is_stored_as_true_not_as_1():
    assert value_columns(True) == (None, None, True)     # bool checked before int
    assert value_columns(3) == (3.0, None, None)
    assert value_columns("heat") == (None, "heat", None)


def test_other_values_are_refused():
    with pytest.raises(Unstorable):
        value_columns([1, 2])


def test_contract_check_finds_problems():
    validate = contract_validator(V01 / "contracts")
    good = json.loads(canonical().payload)
    assert validate(good, "canonical") == []
    bad = {**good, "v": 1}
    assert any("v" in e for e in validate(bad, "canonical"))


def test_unreachable_database_raises_store_unavailable():
    h = PostgresHistorian("postgresql://nobody@127.0.0.1:1/none", "site1")
    with pytest.raises(StoreUnavailable):
        h.write([canonical()])


# --- With a database -----------------------------------------------------------------------

@pytest.fixture
def store():
    import psycopg
    with psycopg.connect(DB) as c:
        c.execute("TRUNCATE readings, quarantine, series RESTART IDENTITY CASCADE")
    h = PostgresHistorian(DB, "site1", validate=contract_validator(V01 / "contracts"),
                          clock=lambda: datetime(2026, 10, 29, 12, tzinfo=timezone.utc))
    h.sync_series("site1", Mapper.from_folder(V01).points())
    yield h
    h.close()


def count(h, table, where="true"):
    with h.conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {table} WHERE {where}")
        n = cur.fetchone()[0]
    h.conn.commit()
    return n


@needs_db
def test_series_come_from_the_asset_model(store):
    assert ("site1", "unit1.energy") in store.series and len(store.series) == 10


@needs_db
def test_reading_is_stored_and_read_back(store):
    r = store.write([canonical(value=21.4)])
    assert (r.readings, r.duplicates, r.quarantined) == (1, 0, 0)
    [row] = store.read("site1", "unit1.zone_air_temp",
                       datetime(2026, 10, 29, tzinfo=timezone.utc), datetime(2026, 10, 30, tzinfo=timezone.utc))
    assert row["value"] == 21.4 and row["quality"] == "GOOD" and row["time_source"] == "device"


@needs_db
def test_duplicate_is_skipped(store):
    store.write([canonical()])
    r = store.write([canonical(), canonical(t="2026-10-29T10:01:00.000Z")])
    assert (r.readings, r.duplicates) == (1, 1)
    assert count(store, "readings") == 2


@needs_db
def test_words_true_false_and_qc_are_kept(store):
    store.write([canonical("unit1.mode_status", "heat", unit=None),
                 canonical(value=40.0, quality="SUSPECT",
                           qc=[{"test": "expected_range", "flag": "SUSPECT", "reason": "40.0 is outside 5..35"}])])
    assert count(store, "readings", "value_text = 'heat'") == 1
    assert count(store, "readings", "qc->0->>'test' = 'expected_range'") == 1


@needs_db
def test_gateway_quarantine_message_is_stored(store):
    q = {"v": 2, "site": "site1", "stage": "map", "reason": "field 'rh' has no point", "topic": "raw/acme/x/telemetry",
         "source": "acme", "device": "x", "field": "rh", "value": 54.0, "raw": "{}", "ingest_time": "2026-10-29T10:00:00.000Z"}
    r = store.write([Message("dt/v1/quarantine/acme", json.dumps(q).encode())])
    assert r.quarantined == 1 and count(store, "quarantine", "stage = 'map'") == 1


@needs_db
@pytest.mark.parametrize("message, why", [
    (Message("dt/v1/telemetry/site1/unit1/zone_air_temp", b"not json"), "not valid JSON"),
    (canonical(point="unit9.nothing"), "no series for site1/unit9.nothing"),
    (Message("dt/v1/telemetry/site1/unit1/zone_air_temp", json.dumps({"v": 1}).encode()), "not a valid canonical"),
])
def test_what_cant_be_stored_goes_to_quarantine_with_the_reason(store, message, why):
    r = store.write([message, canonical()])          # the good one is still stored
    assert r.readings == 1 and r.quarantined == 1 and why in r.problems[0]
    assert count(store, "quarantine", "stage = 'store'") == 1


@needs_db
def test_one_bad_row_does_not_block_the_batch(store):
    # PostgreSQL text can't hold a NUL character: the database refuses that one row.
    poison = canonical("unit1.mode_status", "he\u0000at", unit=None)
    r = store.write([canonical(), poison, canonical(t="2026-10-29T10:02:00.000Z")])
    assert r.readings == 2 and r.quarantined == 1 and "database refused it" in r.problems[0]
