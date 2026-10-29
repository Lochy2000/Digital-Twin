"""
Validator tests: QARTOD-style quality flags (GOOD / SUSPECT / BAD).
Rules and sources: top of gateway/validator.py.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from gateway.decoders import decode
from gateway.mapper import Mapper, MappingError, PointMapping, mapping_files
from gateway.normaliser import normalise
from gateway.validator import validate, with_quality

V01 = Path(__file__).resolve().parents[3]
SAMPLES = Path(__file__).parent / "samples"
SCHEMA = json.loads((V01 / "contracts" / "canonical_message.schema.json").read_text())
T0 = "2026-10-19T08:00:00.000Z"

ZONE = PointMapping("unit1.zone_air_temp", "DEG_C", None, None,
                    fail_span=(-55.0, 125.0), suspect_span=(5.0, 35.0))   # as loaded for the Tasmota probe


def reading(value, sensor_time=T0, ingest_time=T0, point="unit1.zone_air_temp"):
    return {"v": 2, "site": "site1", "point": point, "value": value, "unit": "DEG_C",
            "sensor_time": sensor_time, "ingest_time": ingest_time, "time_source": "device",
            "source": "test:dev1"}


# --- Gross range test -----------------------------------------------------------------

@pytest.mark.parametrize("value, quality", [
    (21.4, "GOOD"),
    (5.0, "GOOD"),          # edges count as inside, as in ioos_qc
    (35.0, "GOOD"),
    (2.0, "SUSPECT"),       # possible, but not in an occupied room
    (40.0, "SUSPECT"),
    (-60.0, "BAD"),         # a DS18B20 can't measure this
    (130.0, "BAD"),
])
def test_gross_range(value, quality):
    assert validate(reading(value), ZONE).quality == quality


def test_worst_flag_wins_and_reasons_are_given():
    v = validate(reading(130.0), ZONE)          # outside BOTH ranges
    assert v.quality == "BAD"
    assert len(v.reasons) == 2 and "sensor's range" in v.reasons[0]


def test_no_ranges_means_only_time_checks():
    bare = PointMapping("unit1.zone_air_temp", "DEG_C", None, None)
    assert validate(reading(999.0), bare).quality == "GOOD"


def test_words_skip_the_range_test():
    mode = PointMapping("unit1.mode_status", None, None, None, {"2": "cool"})
    assert validate(reading("cool", point="unit1.mode_status"), mode).quality == "GOOD"


# --- Time tests -----------------------------------------------------------------------

def test_small_clock_difference_is_allowed():
    assert validate(reading(21.0, sensor_time="2026-10-19T08:00:30.000Z"), ZONE).quality == "GOOD"


def test_reading_from_the_future_is_bad():
    v = validate(reading(21.0, sensor_time="2026-10-19T08:05:00.000Z"), ZONE)
    assert v.quality == "BAD" and "future" in v.reasons[0]


def test_late_reading_is_suspect_not_bad():
    # Step 2j: a late reading is still a real measurement (e.g. replayed after a gateway
    # outage), so it is flagged SUSPECT, not BAD. See the validator header.
    v = validate(reading(21.0, sensor_time="2026-10-19T01:00:00.000Z"), ZONE)   # 7 h old
    assert v.quality == "SUSPECT" and "old" in v.reasons[0]
    assert v.checks[0].test == "late_arrival"


# --- qc list in the message (step 2i) --------------------------------------------------

def test_good_reading_has_no_qc():
    message, _ = with_quality(reading(21.4), ZONE)
    assert message["quality"] == "GOOD" and "qc" not in message


def test_every_flag_is_listed_in_qc():
    message, _ = with_quality(reading(130.0), ZONE)        # outside both ranges
    assert message["quality"] == "BAD"
    assert [(q["test"], q["flag"]) for q in message["qc"]] == [("sensor_range", "BAD"),
                                                              ("expected_range", "SUSPECT")]
    validator = Draft202012Validator(SCHEMA, format_checker=FormatChecker())
    assert not list(validator.iter_errors(message))


def test_stale_check_can_be_turned_off_for_back_fills():
    old = reading(21.0, sensor_time="2026-01-01T00:00:00.000Z")
    assert validate(old, ZONE, max_age=None).quality == "GOOD"


# --- Ranges loaded from the model files ------------------------------------------------

@pytest.fixture(scope="module")
def mapper():
    return Mapper.from_folder(V01, enabled={"acme_hvac_0001": False, "tasmota_zone1": True})


def test_ranges_come_from_type_and_asset_model(mapper):
    m = mapper.lookup("tasmota", "tasmota_zone1", "DS18B20.Temperature")
    assert m.fail_span == (-55.0, 125.0)        # device type: DS18B20 datasheet
    assert m.suspect_span == (5.0, 35.0)        # asset model: zone_temp placeholder


def test_power_range_is_in_the_points_unit(mapper):
    assert mapper.lookup("modbus", "sdm120_unit1", "InputRegister:12").suspect_span == (0.0, 10.0)   # kW


def test_expected_range_wider_than_sensor_range_is_refused(tmp_path):
    extra = tmp_path / "extra.ttl"
    extra.write_text("""
        @prefix dtteo: <urn:dtteo:schema#> . @prefix schema: <http://schema.org/> .
        @prefix unit: <http://qudt.org/vocab/unit/> . @prefix : <urn:dtteo:site1#> .
        :zone_temp dtteo:expectedRange [ schema:minValue -100 ; schema:maxValue 35 ; schema:unitCode unit:DEG_C ] .
    """)
    with pytest.raises(MappingError, match="beyond the sensor's range"):
        Mapper.from_files(V01 / "dtteo_asset_model.ttl", mapping_files(V01) + [extra],
                          {"acme_hvac_0001": False, "tasmota_zone1": True})


def test_range_written_in_fahrenheit_is_converted_to_the_points_unit():
    from gateway.mapper import _Builder
    assert _Builder._span((32, 212, "http://qudt.org/vocab/unit/DEG_F"), "DEG_C", "test") == (0.0, 100.0)


# --- End to end: decode -> map -> normalise -> validate = a complete canonical message ---

def test_full_pipeline_gives_valid_canonical_messages(mapper):
    validator = Draft202012Validator(SCHEMA, format_checker=FormatChecker())
    ingest = datetime(2026, 10, 18, 10, 22, 1, tzinfo=timezone.utc)
    for name in ("tasmota", "sdm120"):
        s = json.loads((SAMPLES / f"{name}.json").read_text())
        for r in decode(s["topic"], json.dumps(s["payload"]).encode(), mapper):
            m = mapper.lookup(r.source, r.device, r.field)
            if m is None:
                continue
            message, verdict = with_quality(normalise(r, m, ingest, "site1"), m)
            assert message["quality"] == "GOOD", verdict.reasons
            assert not list(validator.iter_errors(message)), message
