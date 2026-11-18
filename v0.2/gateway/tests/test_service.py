from pathlib import Path

import gateway.service as service


def test_build_pipeline_uses_configured_model_dir_without_evaluating_fallback(monkeypatch):
    """The shallow /app path in Docker must work when MODEL_DIR is configured."""
    model_dir = str(Path(__file__).resolve().parents[3])
    monkeypatch.setenv("MODEL_DIR", model_dir)
    monkeypatch.setattr(service, "__file__", "/app/gateway/service.py")

    pipeline = service.build_pipeline()

    assert len(pipeline.mapper) == 4      # step 2k: the SDM120 energy register now has a point


# --- Step 2j: a message paho refuses (queue full) is logged, not silently lost ---------------

import logging

import paho.mqtt.client as mqtt

from gateway.pipeline import Outgoing


class FakeClient:
    def __init__(self, rc):
        self.rc = rc

    def publish(self, *args, **kwargs):
        info = mqtt.MQTTMessageInfo(1)
        info.rc = self.rc
        return info


def test_queue_full_is_logged_as_error(caplog):
    o = Outgoing("dt/v1/telemetry/site1/unit1/zone_air_temp", {"point": "unit1.zone_air_temp"})
    with caplog.at_level(logging.ERROR, logger="gateway"):
        service.send(FakeClient(mqtt.MQTT_ERR_QUEUE_SIZE), o)
    assert any(r.message.startswith("publish_dropped") and "unit1.zone_air_temp" in r.message
               for r in caplog.records)


def test_not_connected_is_normal_and_not_logged(caplog):
    # While reconnecting, paho returns NO_CONN but keeps the message and sends it later.
    o = Outgoing("dt/v1/telemetry/site1/unit1/zone_air_temp", {"point": "unit1.zone_air_temp"})
    with caplog.at_level(logging.WARNING, logger="gateway"):
        service.send(FakeClient(mqtt.MQTT_ERR_NO_CONN), o)
    assert not caplog.records
