"""
Tests for the two REAL formats added in step 2f: Tasmota (ESP8266 firmware, JSON over MQTT)
and Modbus register reads (Eastron SDM120 meter). Decode -> map -> normalise -> contract.

Sources for the formats are listed at the top of gateway/decoders/tasmota.py and modbus.py.
"""
import json
import struct
from datetime import datetime, timezone
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from gateway.decoders import DecodeError, decode
from gateway.decoders.modbus import unpack
from gateway.mapper import Mapper, MappingError, mapping_files
from gateway.normaliser import normalise

V01 = Path(__file__).resolve().parents[3]
SAMPLES = Path(__file__).parent / "samples"
INGEST = datetime(2026, 10, 18, 10, 22, 1, tzinfo=timezone.utc)
SCHEMA = json.loads((V01 / "contracts" / "canonical_message.schema.json").read_text())
TASMOTA_TOPIC = "raw/tasmota/tasmota_zone1/tele/SENSOR"


@pytest.fixture(scope="module")
def mapper():
    # Acme off, Tasmota probe on (they feed the same point). The SDM120 is on by default.
    return Mapper.from_folder(V01, enabled={"acme_hvac_0001": False, "tasmota_zone1": True})


def sample(name):
    s = json.loads((SAMPLES / f"{name}.json").read_text())
    return s["topic"], json.dumps(s["payload"]).encode()


def tasmota(payload: dict, registry):
    return {r.field: r for r in decode(TASMOTA_TOPIC, json.dumps(payload).encode(), registry)}


def end_to_end(mapper, topic, payload):
    """{point: canonical reading} for every field the mapper knows."""
    out = {}
    for r in decode(topic, payload, mapper):
        m = mapper.lookup(r.source, r.device, r.field)
        if m:
            out[m.point_id] = normalise(r, m, INGEST, "site1")
    return out


# --- Tasmota ----------------------------------------------------------------------------

def test_tasmota_sample_is_flattened_and_ids_are_metadata(mapper):
    recs = {r.field: r for r in decode(*sample("tasmota"), mapper)}
    assert set(recs) == {"DS18B20.Temperature"}          # Time, TempUnit, DS18B20.Id are metadata
    t = recs["DS18B20.Temperature"]
    assert t.value == 21.4 and t.unit == "DEG_C"


def test_tasmota_local_time_uses_the_bindings_timezone(mapper):
    t = decode(*sample("tasmota"), mapper)[0].time
    assert t == datetime(2026, 10, 18, 10, 22, tzinfo=timezone.utc)    # 11:22 UK summer time


def test_tasmota_without_a_timezone_is_refused():
    with pytest.raises(DecodeError, match="dtteo:timezone"):
        decode(*sample("tasmota"))                       # no registry -> no binding -> no timezone


def test_tasmota_offset_from_setoption52_is_used_directly():
    recs = tasmota({"Time": "2026-10-18T11:22:00+01:00", "DS18B20": {"Temperature": 21.4}}, None)
    assert recs["DS18B20.Temperature"].time == datetime(2026, 10, 18, 10, 22, tzinfo=timezone.utc)


def test_tasmota_hour_that_happens_twice_is_refused(mapper):
    # UK clocks go back at 02:00 on 25 Oct 2026, so 01:30 happens twice.
    with pytest.raises(DecodeError, match="happens twice"):
        tasmota({"Time": "2026-10-25T01:30:00", "DS18B20": {"Temperature": 20.0}}, mapper)


def test_tasmota_fahrenheit_setting_is_converted(mapper):
    payload = {"Time": "2026-10-18T11:22:00", "DS18B20": {"Temperature": 70.52}, "TempUnit": "F"}
    out = end_to_end(mapper, TASMOTA_TOPIC, json.dumps(payload).encode())
    assert out["unit1.zone_air_temp"]["value"] == 21.4                  # 70.52 F
    assert out["unit1.zone_air_temp"]["unit"] == "DEG_C"


def test_tasmota_unknown_temp_unit_is_refused(mapper):
    with pytest.raises(DecodeError, match="TempUnit"):
        tasmota({"Time": "2026-10-18T11:22:00", "DS18B20": {"Temperature": 1}, "TempUnit": "X"}, mapper)


def test_tasmota_last_will_is_plain_text(mapper):
    recs = decode("raw/tasmota/tasmota_zone1/tele/LWT", b"Offline", mapper)
    assert [(r.field, r.value) for r in recs] == [("LWT", "Offline")]   # unmapped -> quarantine


# --- Modbus: unpacking 16-bit words -------------------------------------------------------

def words(value, fmt=">f"):
    b = struct.pack(fmt, value)
    return [int.from_bytes(b[i:i + 2], "big") for i in range(0, len(b), 2)]


def test_unpack_big_endian_float():
    assert unpack([0x448F, 0xD000], "float") == 1150.5                   # 0x448FD000


def test_unpack_word_swapped():
    w = words(1150.5)
    assert unpack(list(reversed(w)), "float", msw_first=False) == 1150.5


def test_unpack_byte_swapped():
    w = [int.from_bytes(x.to_bytes(2, "big")[::-1], "big") for x in words(1150.5)]
    assert unpack(w, "float", msb_first=False) == 1150.5


def test_unpack_wrong_register_count_is_refused():
    with pytest.raises(DecodeError, match="needs 2"):
        unpack([0x448F], "float")


# --- Modbus: SDM120 end to end ------------------------------------------------------------

def test_sdm120_power_register_ends_up_as_kilowatts(mapper):
    out = end_to_end(mapper, *sample("sdm120"))
    p = out["unit1.power"]
    assert (p["value"], p["unit"]) == (1.1505, "KiloW")                  # 1150.5 W
    assert p["sensor_time"] == "2026-10-18T10:22:00.000Z"                # the poller's read time
    assert set(out) == {"unit1.power", "unit1.energy"}                   # the rest have no point yet
    assert (out["unit1.energy"]["value"], out["unit1.energy"]["unit"]) == (2902.25, "KiloW-HR")   # step 2k


def test_sdm120_other_registers_are_decoded_then_quarantined(mapper):
    recs = {r.field: r for r in decode(*sample("sdm120"), mapper)}
    assert round(recs["InputRegister:70"].value, 3) == 50.0              # frequency, decoded
    assert mapper.lookup("modbus", "sdm120_unit1", "InputRegister:70") is None


def test_unknown_register_keeps_its_raw_words(mapper):
    payload = json.dumps({"time": "2026-10-18T10:22:00Z", "registers": {"InputRegister:999": [1, 2]}}).encode()
    [r] = decode("raw/modbus/sdm120_unit1/registers", payload, mapper)
    assert r.value == [1, 2]                                             # nothing lost


def test_modbus_without_a_binding_is_refused():
    with pytest.raises(DecodeError, match="no binding"):
        decode(*sample("sdm120"))


def test_type_with_wrong_register_count_is_refused_at_start_up(tmp_path):
    bad = tmp_path / "bad.ttl"
    bad.write_text("""
        @prefix dtteo: <urn:dtteo:schema#> .  @prefix brick: <https://brickschema.org/schema/Brick#> .
        @prefix modv:  <https://www.w3.org/2019/wot/modbus#> .  @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
        @prefix types: <urn:dtteo:types#> .  @prefix : <urn:dtteo:site1#> .
        types:bad a dtteo:DeviceType ; dtteo:decoder "modbus" ;
            dtteo:hasValue [ modv:entity "InputRegister" ; modv:address 1 ; modv:quantity 1 ;
                             modv:type xsd:float ; dtteo:pointClass brick:Voltage_Sensor ; dtteo:optional true ] .
        :bad a dtteo:DeviceBinding ; dtteo:device "bad" ; dtteo:deviceType types:bad ; dtteo:serves :unit1 .
    """)
    with pytest.raises(MappingError, match="takes 2 register"):
        Mapper.from_files(V01 / "dtteo_asset_model.ttl", mapping_files(V01) + [bad])


# --- Contract ---------------------------------------------------------------------------

def test_real_format_output_is_a_valid_canonical_message(mapper):
    validator = Draft202012Validator(SCHEMA, format_checker=FormatChecker())
    for name in ("tasmota", "sdm120"):
        for reading in end_to_end(mapper, *sample(name)).values():
            errors = [e.message for e in validator.iter_errors({**reading, "quality": "GOOD"})]
            assert not errors, (name, reading["point"], errors)
