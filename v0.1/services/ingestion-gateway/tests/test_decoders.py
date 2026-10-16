"""
Decoder tests. The sample messages in tests/samples/ were captured from the real
vendor scripts in v0.1/testing/vendors/ (same instant: 19:33:38 UTC on 14 Oct 2026).
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from gateway.decoders import DecodeError, decode, parse_raw_topic
from gateway.mapper import Mapper

SAMPLES = Path(__file__).parent / "samples"
V01 = Path(__file__).resolve().parents[3]


def load_sample(name):
    s = json.loads((SAMPLES / f"{name}.json").read_text())
    return s["topic"], json.dumps(s["payload"]).encode()


def by_field(records):
    return {r.field: r for r in records}


# --- topic parsing --------------------------------------------------------------------

def test_parse_raw_topic():
    assert parse_raw_topic("raw/acme/acme_hvac_0001/telemetry") == ("acme", "acme_hvac_0001")


@pytest.mark.parametrize("topic", ["dt/v1/telemetry/x", "raw/acme", "raw//dev/x"])
def test_non_raw_topics_are_rejected(topic):
    with pytest.raises(DecodeError):
        parse_raw_topic(topic)


# --- Acme -----------------------------------------------------------------------------

def test_acme_decodes_every_reading_and_skips_metadata():
    recs = by_field(decode(*load_sample("acme")))
    assert set(recs) == {"tempF", "rh", "op_state"}        # deviceId and ts are not readings
    assert recs["tempF"].value == 70.4                     # untouched: still Fahrenheit
    assert recs["op_state"].value == 2                     # untouched: still Acme's code
    assert recs["tempF"].device == "acme_hvac_0001"        # from the topic


def test_acme_epoch_ms_becomes_a_utc_time():
    t = decode(*load_sample("acme"))[0].time
    assert t == datetime(2026, 10, 14, 19, 33, 38, 428000, tzinfo=timezone.utc)


# --- Borealis -------------------------------------------------------------------------

def test_borealis_flattens_readings_and_status():
    recs = by_field(decode(*load_sample("borealis")))
    assert set(recs) == {"temperature", "humidity", "status.mode"}
    assert recs["temperature"].value == 21.29
    assert recs["status.mode"].value == "COOLING"          # untouched: still Borealis's word


def test_borealis_local_time_keeps_its_offset_and_status_borrows_it():
    recs = by_field(decode(*load_sample("borealis")))
    t = recs["temperature"].time
    assert t.utcoffset().total_seconds() == 3600            # +01:00 kept; normaliser converts to UTC
    assert recs["status.mode"].time == t


# --- Both vendors describe the same moment --------------------------------------------

def test_both_samples_are_the_same_instant():
    acme_t = decode(*load_sample("acme"))[0].time
    bor_t = by_field(decode(*load_sample("borealis")))["temperature"].time
    assert acme_t.replace(microsecond=0) == bor_t           # 19:33:38Z == 20:33:38+01:00


# --- Bad input ------------------------------------------------------------------------

@pytest.mark.parametrize("topic, payload", [
    ("raw/acme/acme_hvac_0001/telemetry", b"not json"),
    ("raw/acme/acme_hvac_0001/telemetry", b"[1, 2, 3]"),
    ("raw/acme/acme_hvac_0001/telemetry", b'{"ts": "yesterday", "tempF": 70}'),
    ("raw/borealis/site4_hvac_01/data", b'{"readings": [{"value": 21}]}'),          # no metric
    ("raw/borealis/site4_hvac_01/data", b'{"readings": [{"metric": "t", "value": 1, "time": "2026-10-14T12:00:00"}]}'),  # no timezone
    ("raw/unknown_vendor/dev1/data", b"{}"),
])
def test_undecodable_messages_raise(topic, payload):
    with pytest.raises(DecodeError):
        decode(topic, payload)


# --- Decoder + mapper together: the key promise -----------------------------------------

def test_two_vendors_end_up_on_the_same_points():
    # Only one of the two may be enabled at a time (step 2e), so one mapper each.
    mappers = {"acme": Mapper.from_folder(V01),
               "borealis": Mapper.from_folder(V01, enabled={"acme_hvac_0001": False, "site4_hvac_01": True})}

    def mapped(name):
        mapper = mappers[name]
        found, unknown = set(), set()
        for r in decode(*load_sample(name)):
            m = mapper.lookup(r.source, r.device, r.field)
            (found.add(m.point_id) if m else unknown.add(r.field))
        return found, unknown

    acme_points, acme_unknown = mapped("acme")
    bor_points, bor_unknown = mapped("borealis")

    assert acme_points == bor_points == {"unit1.zone_air_temp", "unit1.mode_status"}
    assert acme_unknown == {"rh"}            # humidity -> quarantine
    assert bor_unknown == {"humidity"}       # humidity -> quarantine
