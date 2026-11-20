import pytest

from dtnode.config import ConfigError, load

GOOD = 'name = "lab_lepton"\n[broker]\nhost = "hub.local"\n[[sensors]]\nid = "lepton"\ntype = "simulated"\n'


def test_a_good_config_and_env_overrides(tmp_path):
    (tmp_path / "n.toml").write_text(GOOD)
    c = load(tmp_path / "n.toml", env={"BROKER_HOST": "broker", "MQTT_PASSWORD": "pw"})
    assert (c.name, c.broker_host, c.broker_port, c.password) == ("lab_lepton", "broker", 1883, "pw")
    assert c.topic == "raw/dtedge/lab_lepton/telemetry" and c.status_topic == "dt/v1/status/lab_lepton"
    assert "pw" not in repr(c)


def test_every_problem_is_reported_at_once(tmp_path):
    (tmp_path / "n.toml").write_text('name = "Lab Lepton"\n[[sensors]]\nid = "a"\ntype = "x"\n[[sensors]]\nid = "a"\n')
    with pytest.raises(ConfigError) as e:
        load(tmp_path / "n.toml", env={})
    assert "name" in str(e.value) and "used twice" in str(e.value) and "no type" in str(e.value)
