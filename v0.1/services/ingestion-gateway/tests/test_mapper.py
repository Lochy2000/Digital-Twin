"""
Mapper tests. Run from services/ingestion-gateway:   python -m pytest -q

These use the REAL asset model and mapping files, so a broken edit to either
shows up here straight away.
"""
from pathlib import Path

import pytest

from gateway.mapper import Mapper, MappingError

V01 = Path(__file__).resolve().parents[3]          # .../v0.1
ASSET_MODEL = V01 / "dtteo_asset_model.ttl"
MAPPINGS = sorted((V01 / "mappings").glob("*.ttl"))


@pytest.fixture(scope="module")
def mapper():
    return Mapper.from_files(ASSET_MODEL, MAPPINGS)


def test_acme_temperature_maps_to_zone_temp(mapper):
    m = mapper.lookup("acme", "acme_hvac_0001", "tempF")
    assert m.point_id == "unit1.zone_air_temp"
    assert m.unit == "DEG_C"
    assert m.raw_unit == "DEG_F"          # normaliser will convert F -> C


def test_borealis_temperature_maps_to_the_same_point(mapper):
    # The key promise: a different vendor, a different field name, the SAME point.
    m = mapper.lookup("borealis", "site4_hvac_01", "temperature")
    assert m.point_id == "unit1.zone_air_temp"
    assert m.raw_unit is None             # already Celsius


def test_both_vendors_mode_maps_to_mode_status(mapper):
    assert mapper.lookup("acme", "acme_hvac_0001", "op_state").point_id == "unit1.mode_status"
    assert mapper.lookup("borealis", "site4_hvac_01", "status.mode").point_id == "unit1.mode_status"
    assert mapper.lookup("acme", "acme_hvac_0001", "op_state").unit is None   # a mode has no unit


@pytest.mark.parametrize("source, device, field", [
    ("acme", "acme_hvac_0001", "rh"),               # humidity: not in the asset model
    ("borealis", "site4_hvac_01", "humidity"),      # same, other vendor
    ("acme", "some_other_device", "tempF"),         # right field, unknown device
    ("unknown_vendor", "acme_hvac_0001", "tempF"),  # unknown source
])
def test_unknown_fields_return_none(mapper, source, device, field):
    assert mapper.lookup(source, device, field) is None    # -> quarantine


def test_same_field_mapped_to_two_points_is_rejected(tmp_path):
    clash = tmp_path / "clash.ttl"
    clash.write_text("""
        @prefix dtteo: <urn:dtteo:schema#> .
        @prefix ref:   <https://brickschema.org/schema/Brick/ref#> .
        @prefix :      <urn:dtteo:site1#> .
        :supply_temp ref:hasExternalReference [ a dtteo:RawFieldReference ;
            dtteo:source "acme" ; dtteo:device "acme_hvac_0001" ; dtteo:field "tempF" ] .
    """)
    with pytest.raises(MappingError, match="mapped to both"):
        Mapper.from_files(ASSET_MODEL, MAPPINGS + [clash])
