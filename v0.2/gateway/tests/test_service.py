import gateway.service as service
from support import MODEL, VENDORS
def test_build_pipeline_uses_configured_model_dir_without_evaluating_fallback(monkeypatch):
    """The shallow /app path in Docker must work when MODEL_DIR is configured."""
    monkeypatch.setenv("MODEL_DIR", str(MODEL))
    monkeypatch.setenv("GATEWAY_PLUGINS", str(VENDORS))     # Acme's 2 fields count towards the 4
    monkeypatch.setattr(service, "__file__", "/app/gateway/service.py")

    pipeline = service.build_pipeline()

    assert len(pipeline.mapper) == 33     # 2 Acme + 2 SDM120 (step 2k) + 29 rig fields (v0.2 step C)


def test_without_plugins_only_real_formats_are_mapped(monkeypatch):
    """v0.2 change 7: on the Pi (no GATEWAY_PLUGINS) the fake vendors are not bound at all."""
    monkeypatch.setenv("MODEL_DIR", str(MODEL))
    monkeypatch.delenv("GATEWAY_PLUGINS", raising=False)
    mapper = service.build_pipeline().mapper
    assert mapper.binding("acme", "acme_hvac_0001") is None
    assert mapper.binding("modbus", "sdm120_unit1") is not None


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


# --- v0.2 step D: send() tells the caller which outputs it can wait for ---------------------

def test_send_returns_the_message_id_when_paho_holds_it():
    o = Outgoing("dt/v1/telemetry/site1/unit1/zone_air_temp", {"point": "unit1.zone_air_temp"})
    assert service.send(FakeClient(mqtt.MQTT_ERR_SUCCESS), o) == 1
    assert service.send(FakeClient(mqtt.MQTT_ERR_NO_CONN), o) == 1     # sent after reconnect


def test_send_returns_none_when_the_output_is_lost():
    o = Outgoing("dt/v1/telemetry/site1/unit1/zone_air_temp", {"point": "unit1.zone_air_temp"})
    assert service.send(FakeClient(mqtt.MQTT_ERR_QUEUE_SIZE), o) is None
