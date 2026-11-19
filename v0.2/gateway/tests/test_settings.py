"""v0.2 change 9: every gateway setting is read and checked once, at start-up."""
import pytest

from gateway.settings import Settings, SettingsError
from support import MODEL, VENDORS
def test_defaults_need_nothing_set():
    s = Settings.from_env({})
    assert (s.broker_host, s.broker_port, s.site, s.model_dir) == ("localhost", 1883, "site1", MODEL)
    assert s.plugins is None and s.mqtt_password is None


def test_values_are_read_and_converted():
    s = Settings.from_env({"BROKER_HOST": "gateway-broker", "BROKER_PORT": "1884", "GATEWAY_PLUGINS": str(VENDORS),
                           "GATEWAY_ENABLED": "acme_hvac_0001=off", "LOG_LEVEL": "debug", "MQTT_PASSWORD": "pw"})
    assert s.broker_port == 1884 and s.plugins == VENDORS and s.log_level == "DEBUG"
    assert s.enabled == {"acme_hvac_0001": False}


def test_every_problem_is_reported_at_once():
    with pytest.raises(SettingsError) as e:
        Settings.from_env({"BROKER_PORT": "188e", "GATEWAY_SITE": "Site 1", "MODEL_DIR": "/nowhere",
                           "GATEWAY_PLUGINS": "/nowhere", "GATEWAY_ENABLED": "x=maybe", "LOG_LEVEL": "LOUD"})
    for name in ("BROKER_PORT", "GATEWAY_SITE", "MODEL_DIR", "GATEWAY_PLUGINS", "GATEWAY_ENABLED", "LOG_LEVEL"):
        assert name in str(e.value)


def test_password_is_never_printed_or_logged():
    s = Settings.from_env({"MQTT_PASSWORD": "secret123"})
    assert "secret123" not in repr(s) and "secret123" not in str(s.for_log())
    assert s.for_log()["mqtt_password_set"] is True
