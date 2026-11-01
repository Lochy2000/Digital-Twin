"""
E7: how much work is adding a device?

1. Counts what each device type already added needed: lines of configuration (Turtle) and of
   Python (its decoder; a decoder is shared by every device type that speaks its format).
2. Adds a NEW device type live, in a scratch copy of the model folder: a Tasmota board with a
   BME280 sensor (temperature, humidity, pressure), using the existing Tasmota decoder. Records
   the lines written, whether any Python changed, and whether its first message comes out right.

    python experiments/e7_onboarding.py
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "services" / "ingestion-gateway")]
import harness as h  # noqa: E402
from gateway.mapper import Mapper  # noqa: E402
from gateway.pipeline import Pipeline  # noqa: E402

V01 = h.V01
TYPES = {"acme_hvac": "acme", "borealis_hvac": "borealis", "tasmota_ds18b20": "tasmota", "eastron_sdm120": "modbus"}

NEW_TYPE = """@prefix dtteo: <urn:dtteo:schema#> .
@prefix brick: <https://brickschema.org/schema/Brick#> .
@prefix unit:  <http://qudt.org/vocab/unit/> .
@prefix ssn-system: <http://www.w3.org/ns/ssn/systems/> .
@prefix schema: <http://schema.org/> .
@prefix types: <urn:dtteo:types#> .

types:tasmota_bme280 a dtteo:DeviceType ;
    dtteo:version "1.0.0" ;
    dtteo:decoder "tasmota" ;
    dtteo:manufacturerDoc "https://tasmota.github.io/docs/BME280/" ;
    dtteo:hasValue [
        dtteo:field "BME280.Temperature" ;
        dtteo:pointClass brick:Temperature_Sensor ;
        ssn-system:hasSystemCapability [ ssn-system:hasSystemProperty [
            a ssn-system:MeasurementRange ;
            schema:minValue -40 ; schema:maxValue 85 ; schema:unitCode unit:DEG_C ] ]
    ] , [
        dtteo:field "BME280.Humidity" ;
        dtteo:pointClass brick:Zone_Air_Humidity_Sensor ;
        dtteo:optional true
    ] , [
        dtteo:field "BME280.Pressure" ;
        dtteo:pointClass brick:Pressure_Sensor ;
        dtteo:optional true
    ] .
"""

NEW_BINDING = """
b:tasmota_zone1_bme a dtteo:DeviceBinding ;
    dtteo:device "tasmota_zone1_bme" ;
    dtteo:deviceType types:tasmota_bme280 ;
    dtteo:serves :zone1 ;
    dtteo:place [ dtteo:field "BME280.Temperature" ; dtteo:point :zone_temp ] ;
    dtteo:timezone "Europe/London" .
"""


def lines(text: str) -> int:
    return sum(1 for l in text.splitlines() if l.strip() and not l.strip().startswith("#"))


def main():
    rows = []
    for t, dec in TYPES.items():
        rows.append({"device_type": t, "decoder": dec, "config_lines": lines((V01 / "mappings" / "types" / f"{t}.ttl").read_text()),
                     "decoder_python_lines": lines((V01 / "services" / "ingestion-gateway" / "gateway" / "decoders" / f"{dec}.py").read_text())})

    with tempfile.TemporaryDirectory() as tmp:
        model = Path(tmp)
        shutil.copy(V01 / "dtteo_asset_model.ttl", model)
        shutil.copytree(V01 / "mappings", model / "mappings")
        (model / "mappings" / "types" / "tasmota_bme280.ttl").write_text(NEW_TYPE)
        binding = model / "mappings" / "bindings" / "site1.ttl"
        # only one device may feed the zone temperature: switch Acme off, as an installer would
        binding.write_text(binding.read_text() + NEW_BINDING)
        pipe = Pipeline(Mapper.from_folder(model, enabled={"acme_hvac_0001": False}), site="site1")
        now = datetime(2026, 11, 1, 12, 0, 5, tzinfo=timezone.utc)
        # Tasmota BME280 shape: Tasmota wiki BME280 page (PressureUnit, TempUnit) + DewPoint as in newer
        # firmware (tasmor_lib parser test, docs.rs/crate/tasmor_lib, sensor_parser.rs)
        msg = {"Time": "2026-11-01T12:00:00", "BME280": {"Temperature": 21.7, "Humidity": 48.2, "DewPoint": 10.3, "Pressure": 1012.4},
               "PressureUnit": "hPa", "TempUnit": "C"}
        outs = pipe.process("raw/tasmota/tasmota_zone1_bme/tele/SENSOR", json.dumps(msg).encode(), now)
        result = [{"topic": o.topic, "point": o.payload.get("point"), "value": o.payload.get("value"),
                   "quality": o.payload.get("quality"), "stage": o.payload.get("stage"), "field": o.payload.get("field")} for o in outs]
        skipped = pipe.take_skipped()
    rows.append({"device_type": "tasmota_bme280 (added in this experiment)", "decoder": "tasmota (existing)",
                 "config_lines": lines(NEW_TYPE) + lines(NEW_BINDING), "decoder_python_lines": 0})
    h.write_csv("e7_onboarding.csv", rows)
    (h.RESULTS / "e7_new_device_first_message.json").write_text(json.dumps({"out": result, "counted_not_mapped": skipped}, indent=2))
    for r in rows:
        print(r)
    print(json.dumps(result, indent=1), skipped)


if __name__ == "__main__":
    print(h.stamp(), "E7")
    main()
