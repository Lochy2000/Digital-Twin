"""
Pipeline tests: one raw message in -> what gets published, without a broker.
Every outgoing message is checked against its contract schema.
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from gateway.mapper import Mapper
from gateway.pipeline import Pipeline, kv, telemetry_topic
from gateway.service import parse_enabled

V01 = Path(__file__).resolve().parents[3]
SAMPLES = Path(__file__).parent / "samples"
CONTRACTS = V01 / "contracts"
CANONICAL = Draft202012Validator(json.loads((CONTRACTS / "canonical_message.schema.json").read_text()),
                                 format_checker=FormatChecker())
QUARANTINE = Draft202012Validator(json.loads((CONTRACTS / "quarantine_message.schema.json").read_text()),
                                  format_checker=FormatChecker())


@pytest.fixture(scope="module")
def pipeline():
    # Recorded samples are old, so the stale-data check is off (as in the demo).
    return Pipeline(Mapper.from_folder(V01), site="site1", max_age=None)


def run(pipeline, topic, payload, now=datetime(2026, 10, 14, 19, 33, 39, tzinfo=timezone.utc)):
    out = pipeline.process(topic, payload if isinstance(payload, bytes) else json.dumps(payload).encode(), now)
    for o in out:   # every message must match its contract
        schema = QUARANTINE if o.topic.startswith("dt/v1/quarantine/") else CANONICAL
        assert not list(schema.iter_errors(o.payload)), (o.topic, o.payload)
        assert o.qos == 1 and o.retain is False
    return out


def sample(name):
    s = json.loads((SAMPLES / f"{name}.json").read_text())
    return s["topic"], s["payload"]


def test_acme_message_becomes_telemetry_and_quarantine(pipeline):
    out = {o.topic: o.payload for o in run(pipeline, *sample("acme"))}
    assert out["dt/v1/telemetry/site1/unit1/zone_air_temp"]["value"] == 21.3333
    assert out["dt/v1/telemetry/site1/unit1/mode_status"]["value"] == "cool"
    q = out["dt/v1/quarantine/acme"]                       # humidity: no point
    assert (q["stage"], q["field"], q["value"]) == ("map", "rh", 54.0)
    assert "no brick:Zone_Air_Humidity_Sensor point" in q["reason"]   # says exactly what is missing
    assert json.loads(q["raw"])["tempF"] == 70.4           # original kept for replay


def test_messages_carry_site_and_time_source(pipeline):
    out = {o.topic: o.payload for o in run(pipeline, *sample("acme"))}
    t = out["dt/v1/telemetry/site1/unit1/zone_air_temp"]
    assert (t["v"], t["site"], t["time_source"]) == (2, "site1", "device")
    assert out["dt/v1/quarantine/acme"]["site"] == "site1"


def test_gateway_bug_quarantines_the_message_instead_of_losing_it(pipeline, monkeypatch, caplog):
    # Step 2j: any unexpected error -> stage "internal", original kept for replay.
    def boom(*_):
        raise RuntimeError("simulated bug")
    monkeypatch.setattr(pipeline, "_process", boom)
    with caplog.at_level(logging.ERROR, logger="gateway"):
        [q] = run(pipeline, "raw/acme/acme_hvac_0001/telemetry", b'{"tempF": 70}')
    assert q.topic == "dt/v1/quarantine/acme"
    assert q.payload["stage"] == "internal" and "simulated bug" in q.payload["reason"]
    assert q.payload["raw"] == '{"tempF": 70}'
    assert any(r.message.startswith("pipeline_error") for r in caplog.records)


def test_topic_follows_the_contract():
    assert telemetry_topic("site1", "unit1.zone_air_temp") == "dt/v1/telemetry/site1/unit1/zone_air_temp"


def test_message_that_cant_be_read_is_quarantined_whole(pipeline):
    [q] = run(pipeline, "raw/acme/acme_hvac_0001/telemetry", b"not json")
    assert q.topic == "dt/v1/quarantine/acme"
    assert q.payload["stage"] == "decode" and q.payload["raw"] == "not json"


def test_bad_topic_goes_to_unknown(pipeline):
    [q] = run(pipeline, "raw/Bad Source", b"{}")
    assert q.topic == "dt/v1/quarantine/unknown" and q.payload["source"] is None


def test_disabled_binding_says_so(pipeline):
    out = run(pipeline, *sample("borealis"))               # Borealis is off by default
    assert all(o.topic == "dt/v1/quarantine/borealis" for o in out)
    assert "disabled" in out[0].payload["reason"]


def test_unknown_device_says_so(pipeline):
    [q] = run(pipeline, "raw/acme/acme_hvac_9999/telemetry", {"ts": 1792006418428, "tempF": 70.0})
    assert "not bound" in q.payload["reason"]


def test_field_not_in_the_type_says_so(pipeline):
    [q] = run(pipeline, "raw/acme/acme_hvac_0001/telemetry", {"ts": 1792006418428, "co2": 410})
    assert "not in device type acme_hvac" in q.payload["reason"]


def test_value_not_in_value_map_is_quarantined_at_normalise(pipeline):
    out = run(pipeline, "raw/acme/acme_hvac_0001/telemetry", {"ts": 1792006418428, "op_state": 9})
    assert out[0].payload["stage"] == "normalise" and "value map" in out[0].payload["reason"]


def test_bad_reading_is_published_not_quarantined(pipeline, caplog):
    # 200 F = 93 C: understood, but outside the expected range -> SUSPECT, still published.
    with caplog.at_level(logging.INFO, logger="gateway"):
        [t, _] = run(pipeline, "raw/acme/acme_hvac_0001/telemetry",
                     {"ts": 1792006418428, "tempF": 200.0, "op_state": 1})
    assert t.topic == "dt/v1/telemetry/site1/unit1/zone_air_temp"
    assert t.payload["quality"] == "SUSPECT"
    assert t.payload["qc"][0]["test"] == "expected_range"   # the reason travels with the data
    # The log line says why (what you asked for: logs explain each message).
    assert any("quality=SUSPECT" in r.message and "expected range" in r.message for r in caplog.records)


def test_quarantine_is_logged_with_reason(pipeline, caplog):
    with caplog.at_level(logging.WARNING, logger="gateway"):
        run(pipeline, *sample("acme"))
    [line] = [r.message for r in caplog.records if r.message.startswith("quarantine")]
    assert "stage=map" in line and "field=rh" in line and "reason=" in line


def test_logfmt_quotes_values_with_spaces():
    assert kv("x", a=1, b="two words", c=None) == 'x a=1 b="two words"'


def test_enabled_overrides_from_environment():
    assert parse_enabled("acme_hvac_0001=off, site4_hvac_01=on") == {"acme_hvac_0001": False, "site4_hvac_01": True}
    with pytest.raises(ValueError):
        parse_enabled("acme_hvac_0001=maybe")
