"""v0.2 step C: the lab rig (dt-edge) through the gateway. Sample: tests/samples/dtedge.json."""
import json
from datetime import datetime, timezone

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from gateway.decoders import DecodeError, decode
from gateway.pipeline import Pipeline
from support import CONTRACTS, model_mapper, sample_file
SAMPLE = json.loads(sample_file("dtedge").read_text())
TOPIC = SAMPLE["topic"]
NOW = datetime(2026, 11, 8, 21, 0, 1, tzinfo=timezone.utc)
SCHEMA = Draft202012Validator(json.loads((CONTRACTS / "canonical_message.schema.json").read_text()),
                              format_checker=FormatChecker())


def run(payload, now=NOW):
    out = Pipeline(model_mapper(), site="site1").process(TOPIC, json.dumps(payload).encode(), now)
    return {o.payload.get("point") or o.payload.get("field"): o for o in out}


def reading(point_id, value, unit="DEG_C", **extra):
    return {"v": 2, "site": "rig1", "point_id": point_id, "value": value, "unit": unit,
            "sensor_time": "2026-11-08T21:00:00+00:00", "quality": "GOOD", "qc": None, **extra}


# --- decoder ---------------------------------------------------------------------------------

def test_a_list_and_a_single_reading_both_decode():
    many = decode(TOPIC, json.dumps(SAMPLE["payload"]).encode())
    one = decode(TOPIC, json.dumps(SAMPLE["payload"][0]).encode())
    assert len(many) == len(SAMPLE["payload"]) and len(one) == 1
    assert (one[0].field, one[0].device, one[0].unit) == ("tc08.ch1", "digitwin_pi", "DEG_C")


@pytest.mark.parametrize("bad", [
    b"not json", b"[]", b"[1]",
    json.dumps(reading("tc08.ch1", 1, v=1)).encode(),                              # wrong version
    json.dumps({k: v for k, v in reading("tc08.ch1", 1).items() if k != "value"}).encode(),
    json.dumps(reading("tc08.ch1", 1, sensor_time="2026-11-08T21:00:00")).encode(),  # no UTC offset
    json.dumps(reading("tc08.ch1", 1, quality="MAYBE")).encode(),
])
def test_messages_it_cannot_understand_raise(bad):
    with pytest.raises(DecodeError):
        decode(TOPIC, bad)


# --- through the whole pipeline ------------------------------------------------------------

def test_every_rig_reading_becomes_a_valid_canonical_message():
    out = run(SAMPLE["payload"])
    assert all(o.topic.startswith("dt/v1/telemetry/site1/rig1/") for o in out.values())
    assert len(out) == len(SAMPLE["payload"])
    for o in out.values():
        assert not list(SCHEMA.iter_errors(o.payload)), o.payload


def test_points_units_and_values():
    out = {p: o.payload for p, o in run(SAMPLE["payload"]).items()}
    assert out["rig1.tc_ch1"]["value"] == 28.4 and out["rig1.tc_ch1"]["unit"] == "DEG_C"
    assert out["rig1.room_humidity"]["unit"] == "PERCENT_RH"
    assert out["rig1.room_pressure"]["value"] == 1012.4 and out["rig1.room_pressure"]["unit"] == "HectoPA"
    assert out["rig1.plug_on"]["value"] is True
    assert out["rig1.tc_ch1"]["sensor_time"] == "2026-11-08T21:00:00.123Z"      # UTC, milliseconds
    assert out["rig1.tc_ch1"]["source"] == "dtedge:digitwin_pi"
    assert out["rig1.tc_ch1"]["site"] == "site1"                                  # the gateway's site, not dt-edge's


def test_the_devices_own_flag_is_kept_as_a_check():
    mlx = run(SAMPLE["payload"])["rig1.mlx_mean"].payload
    assert mlx["quality"] == "SUSPECT"
    assert any(c["test"] == "device_flag" and "bad_pixels" in c["reason"] for c in mlx["qc"])


def test_device_bad_makes_it_bad_even_if_the_value_looks_fine():
    p = run([reading("tc08.ch2", 25.0, quality="BAD", qc=["read_error"])])["rig1.tc_ch2"].payload
    assert p["quality"] == "BAD"


def test_gateway_checks_still_run_on_rig_data():
    p = run([reading("tc08.ch3", 1500.0)])["rig1.tc_ch3"].payload               # beyond type K's range
    assert p["quality"] == "BAD" and p["qc"][0]["test"] == "sensor_range"


def test_null_value_is_quarantined_not_stored():
    q = run([reading("tc08.ch4", None, quality="BAD")])["tc08.ch4"]
    assert q.topic == "dt/v1/quarantine/dtedge" and "no value" in q.payload["reason"]


def test_a_field_the_type_does_not_list_is_quarantined():
    q = run([reading("mlx.spot1", 22.0)])["mlx.spot1"]
    assert q.topic == "dt/v1/quarantine/dtedge" and "not in device type dtedge_rig" in q.payload["reason"]


def test_an_unbound_node_is_quarantined():
    out = Pipeline(model_mapper(), site="site1").process(
        "raw/dtedge/some_other_pi/telemetry", json.dumps(reading("tc08.ch1", 20.0)).encode(), NOW)
    assert out[0].topic == "dt/v1/quarantine/dtedge" and "not bound" in out[0].payload["reason"]
