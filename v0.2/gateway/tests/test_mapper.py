"""
Mapper tests. Run from services/ingestion-gateway:   python -m pytest -q

These use the REAL asset model, device types and bindings, so a broken edit to any
of them shows up here straight away. The rule tests add one small extra file on top.
"""
from pathlib import Path

import pytest

from gateway.mapper import Mapper, MappingError, mapping_files

V01 = Path(__file__).resolve().parents[3]          # .../v0.1
ASSET_MODEL = V01 / "dtteo_asset_model.ttl"
SWAP_TO_BOREALIS = {"acme_hvac_0001": False, "site4_hvac_01": True}
SWAP_TO_TASMOTA = {"acme_hvac_0001": False, "tasmota_zone1": True}

HEAD = """
@prefix dtteo: <urn:dtteo:schema#> .
@prefix brick: <https://brickschema.org/schema/Brick#> .
@prefix ref:   <https://brickschema.org/schema/Brick/ref#> .
@prefix types: <urn:dtteo:types#> .
@prefix :      <urn:dtteo:site1#> .
"""


@pytest.fixture(scope="module")
def mapper():
    return Mapper.from_folder(V01)                 # exactly as bindings/site1.ttl says


def with_extra(tmp_path, ttl, enabled=None):
    """A mapper from the real files plus one extra Turtle snippet."""
    extra = tmp_path / "extra.ttl"
    extra.write_text(HEAD + ttl)
    return Mapper.from_files(ASSET_MODEL, mapping_files(V01) + [extra], enabled)


# --- Fake vendors, now via device types + bindings -------------------------------------

def test_acme_temperature_maps_to_zone_temp(mapper):
    m = mapper.lookup("acme", "acme_hvac_0001", "tempF")
    assert m.point_id == "unit1.zone_air_temp"     # found by Brick class, via unit1 -feeds-> zone1
    assert m.unit == "DEG_C"
    assert m.raw_unit == "DEG_F"


def test_acme_mode_has_its_value_map(mapper):
    m = mapper.lookup("acme", "acme_hvac_0001", "op_state")
    assert m.point_id == "unit1.mode_status"
    assert m.unit is None
    assert m.value_map == {"1": "heat", "2": "cool", "3": "off"}


def test_borealis_is_disabled_by_default(mapper):
    assert mapper.lookup("borealis", "site4_hvac_01", "temperature") is None    # -> quarantine
    assert mapper.binding("borealis", "site4_hvac_01").enabled is False


def test_swapping_to_borealis_gives_the_same_points():
    m = Mapper.from_folder(V01, enabled=SWAP_TO_BOREALIS)
    assert m.lookup("borealis", "site4_hvac_01", "temperature").point_id == "unit1.zone_air_temp"
    assert m.lookup("borealis", "site4_hvac_01", "status.mode").value_map == {"HEATING": "heat", "COOLING": "cool"}
    assert m.lookup("acme", "acme_hvac_0001", "tempF") is None


# --- Real formats -----------------------------------------------------------------------

def test_sdm120_power_register_maps_to_unit_power(mapper):
    m = mapper.lookup("modbus", "sdm120_unit1", "InputRegister:12")     # field built from modv terms
    assert m.point_id == "unit1.power"
    assert (m.unit, m.raw_unit) == ("KiloW", "W")


def test_optional_values_without_a_point_are_reported_not_mapped(mapper):
    assert mapper.lookup("modbus", "sdm120_unit1", "InputRegister:0") is None    # voltage
    assert mapper.lookup("acme", "acme_hvac_0001", "rh") is None               # humidity
    assert any("InputRegister:0" in line and "Voltage_Sensor" in line for line in mapper.report)


def test_binding_carries_instance_details(mapper):
    sdm = mapper.binding("modbus", "sdm120_unit1")
    assert sdm.base == "modbus+tcp://192.168.1.50:502/1" and sdm.device_type == "eastron_sdm120"
    tas = mapper.binding("tasmota", "tasmota_zone1")
    assert tas.timezone == "Europe/London" and tas.serves == "zone1"


def test_tasmota_probe_is_placed_on_the_zone_temperature():
    m = Mapper.from_folder(V01, enabled=SWAP_TO_TASMOTA)
    assert m.lookup("tasmota", "tasmota_zone1", "DS18B20.Temperature").point_id == "unit1.zone_air_temp"


@pytest.mark.parametrize("source, device, field", [
    ("acme", "some_other_device", "tempF"),         # right field, unbound device
    ("unknown_vendor", "acme_hvac_0001", "tempF"),  # unknown source
    ("acme", "acme_hvac_0001", "not_a_field"),      # field the type doesn't list
])
def test_unknown_fields_return_none(mapper, source, device, field):
    assert mapper.lookup(source, device, field) is None    # -> quarantine


# --- The start-up rules -----------------------------------------------------------------

def test_rule1_binding_to_a_missing_type_is_rejected(tmp_path):
    with pytest.raises(MappingError, match="does not exist"):
        with_extra(tmp_path, ':x a dtteo:DeviceBinding ; dtteo:device "x" ; '
                             'dtteo:deviceType types:no_such_type ; dtteo:serves :unit1 .')


def test_rule1_a_device_has_exactly_one_type(tmp_path):
    with pytest.raises(MappingError, match="ONE type"):
        with_extra(tmp_path, ':x a dtteo:DeviceBinding ; dtteo:device "x" ; dtteo:serves :unit1 ; '
                             'dtteo:deviceType types:acme_hvac, types:borealis_hvac .')


def test_rule2_required_value_with_no_point_is_rejected(tmp_path):
    ttl = """
        types:co2 a dtteo:DeviceType ; dtteo:decoder "acme" ;
            dtteo:hasValue [ dtteo:field "co2" ; dtteo:pointClass brick:CO2_Sensor ] .
        :x a dtteo:DeviceBinding ; dtteo:device "x" ; dtteo:deviceType types:co2 ; dtteo:serves :unit1 .
    """
    with pytest.raises(MappingError, match="has no brick:CO2_Sensor point"):
        with_extra(tmp_path, ttl)


def test_rule3_two_enabled_devices_on_one_point_is_rejected():
    with pytest.raises(MappingError, match="only one may be enabled"):
        Mapper.from_folder(V01, enabled={"site4_hvac_01": True})          # Acme AND Borealis on


def test_two_matching_points_must_be_placed(tmp_path):
    ttl = """
        :zone1 brick:hasPoint :zone_temp2 .
        :zone_temp2 a brick:Zone_Air_Temperature_Sensor ; dtteo:valueKind "measurement" ;
            ref:hasExternalReference [ a ref:TimeseriesReference ; ref:hasTimeseriesId "zone1.temp2" ] .
    """
    with pytest.raises(MappingError, match="dtteo:place"):
        with_extra(tmp_path, ttl)


def test_placing_a_field_the_type_lacks_is_rejected(tmp_path):
    ttl = ':x a dtteo:DeviceBinding ; dtteo:device "x" ; dtteo:deviceType types:acme_hvac ; ' \
          'dtteo:serves :unit1 ; dtteo:enabled false ; dtteo:place [ dtteo:field "typo" ; dtteo:point :power ] .'
    with pytest.raises(MappingError, match="does not have"):
        with_extra(tmp_path, ttl)


# --- Route 1 (per-field references, for irregular sources) still works ------------------

def test_per_field_reference_still_works(tmp_path):
    m = with_extra(tmp_path, ':supply_temp ref:hasExternalReference [ a dtteo:RawFieldReference ; '
                             'dtteo:source "bms_csv" ; dtteo:device "site1_bms" ; dtteo:field "AHU-1 SAT" ] .')
    assert m.lookup("bms_csv", "site1_bms", "AHU-1 SAT").point_id == "unit1.supply_air_temp"


def test_same_field_mapped_to_two_points_is_rejected(tmp_path):
    with pytest.raises(MappingError, match="mapped to both"):
        with_extra(tmp_path, ':supply_temp ref:hasExternalReference [ a dtteo:RawFieldReference ; '
                             'dtteo:source "acme" ; dtteo:device "acme_hvac_0001" ; dtteo:field "tempF" ] .')


# --- Step 2k: value kinds and the energy point ---------------------------------------------

def test_every_point_has_a_kind_and_energy_is_a_total():
    m = Mapper.from_folder(V01)
    kinds = {p.point_id: p.kind for p in m.points()}
    assert kinds["unit1.energy"] == "total"
    assert kinds["unit1.mode_status"] == "state"
    assert kinds["unit1.zone_air_temp"] == "measurement"
    assert "weather1.outside_air_temp" in kinds          # renamed from site1.outside_air_temp


def test_sdm120_energy_register_now_maps_to_kwh():
    pm = Mapper.from_folder(V01).lookup("modbus", "sdm120_unit1", "InputRegister:72")
    assert (pm.point_id, pm.unit, pm.raw_unit) == ("unit1.energy", "KiloW-HR", "KiloW-HR")


def test_point_without_a_kind_is_refused(tmp_path):
    extra = tmp_path / "extra.ttl"
    extra.write_text("""
        @prefix brick: <https://brickschema.org/schema/Brick#> .
        @prefix ref: <https://brickschema.org/schema/Brick/ref#> . @prefix : <urn:dtteo:site1#> .
        :humidity a brick:Zone_Air_Humidity_Sensor ;
            ref:hasExternalReference [ a ref:TimeseriesReference ; ref:hasTimeseriesId "unit1.zone_humidity" ] .
    """)
    with pytest.raises(MappingError, match="unit1.zone_humidity: dtteo:valueKind must be one of"):
        Mapper.from_files(V01 / "dtteo_asset_model.ttl", mapping_files(V01) + [extra])
