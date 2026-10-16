"""
Normaliser tests: decode -> map -> normalise, using the real sample messages,
mapping files and asset model. Ends with a contract check against the canonical schema.
"""
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from gateway.decoders import RawRecord, decode
from gateway.mapper import Mapper, PointMapping
from gateway.normaliser import NormaliseError, normalise

V01 = Path(__file__).resolve().parents[3]
SAMPLES = Path(__file__).parent / "samples"
INGEST = datetime(2026, 10, 14, 19, 33, 38, 900000, tzinfo=timezone.utc)
SCHEMA = json.loads((V01 / "contracts" / "canonical_message.schema.json").read_text())


@pytest.fixture(scope="module")
def mapper():
    # Acme and Borealis pretend to be the same unit, so only one may be enabled at a
    # time (step 2e, rule 3). One mapper per vendor, as if swapping the device.
    return {
        "acme": Mapper.from_folder(V01),                       # as in bindings/site1.ttl
        "borealis": Mapper.from_folder(V01, enabled={"acme_hvac_0001": False, "site4_hvac_01": True}),
    }


def run(mapper, sample):
    """Decode a sample, normalise every field the mapper knows. Returns {point: reading}."""
    s = json.loads((SAMPLES / f"{sample}.json").read_text())
    out = {}
    for r in decode(s["topic"], json.dumps(s["payload"]).encode()):
        m = mapper[sample].lookup(r.source, r.device, r.field)
        if m:
            out[m.point_id] = normalise(r, m, INGEST)
    return out


# --- Acme: needs everything converted ---------------------------------------------------

def test_acme_temperature_becomes_celsius_in_utc(mapper):
    t = run(mapper, "acme")["unit1.zone_air_temp"]
    assert t["value"] == 21.3333                      # 70.4 F
    assert t["unit"] == "DEG_C"
    assert t["sensor_time"] == "2026-10-14T19:33:38.428Z"
    assert t["ingest_time"] == "2026-10-14T19:33:38.900Z"
    assert t["source"] == "acme:acme_hvac_0001"


def test_acme_mode_code_becomes_a_word(mapper):
    m = run(mapper, "acme")["unit1.mode_status"]
    assert m["value"] == "cool"                       # op_state 2
    assert m["unit"] is None


# --- Borealis: already Celsius, but local time and capital words ------------------------

def test_borealis_local_time_becomes_utc(mapper):
    t = run(mapper, "borealis")["unit1.zone_air_temp"]
    assert t["value"] == 21.29                        # unchanged: already Celsius
    assert t["sensor_time"] == "2026-10-14T19:33:38.000Z"   # was 20:33:38+01:00


def test_borealis_mode_word_becomes_ours(mapper):
    assert run(mapper, "borealis")["unit1.mode_status"]["value"] == "cool"   # COOLING


# --- The key promise ------------------------------------------------------------------

def test_both_vendors_now_produce_the_same_shape(mapper):
    acme, bor = run(mapper, "acme"), run(mapper, "borealis")
    assert acme.keys() == bor.keys()
    for point in acme:
        a, b = acme[point], bor[point]
        assert a["unit"] == b["unit"]
        assert type(a["value"]) is type(b["value"])
        assert a["sensor_time"].endswith("Z") and b["sensor_time"].endswith("Z")
    assert acme["unit1.mode_status"]["value"] == bor["unit1.mode_status"]["value"] == "cool"


# --- Contract check: output + quality must be a valid canonical message -----------------

def test_output_is_a_valid_canonical_message(mapper):
    validator = Draft202012Validator(SCHEMA, format_checker=FormatChecker())
    for sample in ("acme", "borealis"):
        for reading in run(mapper, sample).values():
            message = {**reading, "quality": "GOOD"}          # the validator (next step) sets this
            errors = [e.message for e in validator.iter_errors(message)]
            assert not errors, (sample, reading["point"], errors)


# --- Things that must go to quarantine --------------------------------------------------

def rec(value, time=INGEST):
    return RawRecord("test", "dev1", "f", value, time)


def test_word_not_in_value_map_is_refused():
    m = PointMapping("unit1.mode_status", None, None, None, {"HEATING": "heat", "COOLING": "cool"})
    with pytest.raises(NormaliseError, match="not in the value map"):
        normalise(rec("OFF"), m, INGEST)


@pytest.mark.parametrize("bad", ["21.5", None, True, [21.5]])
def test_non_numbers_are_refused_for_numeric_points(bad):
    m = PointMapping("unit1.zone_air_temp", "DEG_C", None, None)
    with pytest.raises(NormaliseError, match="expected a number"):
        normalise(rec(bad), m, INGEST)


def test_wrong_kind_of_unit_is_refused():
    m = PointMapping("unit1.zone_air_temp", "DEG_C", "KiloW", None)
    with pytest.raises(NormaliseError, match="can't convert"):
        normalise(rec(5.0), m, INGEST)


# --- Smaller behaviours -----------------------------------------------------------------

def test_scale_is_applied_first():
    # The D-04 diagram's example: a device that sends 2152 meaning 21.52 °C
    m = PointMapping("unit1.zone_air_temp", "DEG_C", None, Decimal("0.01"))
    assert normalise(rec(2152), m, INGEST)["value"] == 21.52


def test_missing_device_time_uses_ingest_time():
    m = PointMapping("unit1.zone_air_temp", "DEG_C", None, None)
    out = normalise(rec(21.0, time=None), m, INGEST)
    assert out["sensor_time"] == out["ingest_time"] == "2026-10-14T19:33:38.900Z"
