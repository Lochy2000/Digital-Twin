"""
The node's settings: node.toml (what this device has) + environment (secrets).

    name = "lab_lepton"                    # this node's login on the broker and its topic level
    [broker]   host, port                  # env BROKER_HOST / BROKER_PORT override
    [outbox]   path, max_messages
    [[sensors]] id, type, poll_s, + the adapter's own settings

The password never goes in the file: env MQTT_PASSWORD (the broker's MQTT_DEVICE_PASSWORD for now).
TOML is read by Python itself (tomllib, 3.11+), so no extra package. Checked at start-up;
every problem is reported at once.
"""
from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

NAME = re.compile(r"^[a-z0-9_]+$")          # a topic level and a broker login (contracts/topics.md rule 2)


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class NodeConfig:
    name: str
    broker_host: str
    broker_port: int
    outbox_path: Path
    outbox_max: int
    sensors: list[dict]
    password: str | None = field(default=None, repr=False)

    @property
    def topic(self) -> str:
        return f"raw/dtedge/{self.name}/telemetry"

    @property
    def status_topic(self) -> str:
        return f"dt/v1/status/{self.name}"


def load(path: Path | str, env=os.environ) -> NodeConfig:
    path = Path(path)
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise ConfigError(f"{path}: {e}") from e
    problems = []
    name = str(data.get("name", ""))
    if not NAME.match(name):
        problems.append(f"name must be lowercase letters, digits and _ (got {name!r})")
    broker = data.get("broker", {})
    host = env.get("BROKER_HOST") or broker.get("host", "localhost")
    try:
        port = int(env.get("BROKER_PORT") or broker.get("port", 1883))
    except ValueError:
        port, _ = 0, problems.append("broker port must be a number")
    outbox = data.get("outbox", {})
    sensors = data.get("sensors", [])
    if not sensors:
        problems.append("no [[sensors]] listed")
    seen = set()
    for i, s in enumerate(sensors):
        sid = s.get("id")
        if not sid or not NAME.match(str(sid)):
            problems.append(f"sensor {i + 1}: id must be lowercase letters, digits and _ (got {sid!r})")
        elif sid in seen:
            problems.append(f"sensor id {sid!r} is used twice")
        seen.add(sid)
        if not s.get("type"):
            problems.append(f"sensor {sid or i + 1}: no type")
        if float(s.get("poll_s", 1)) <= 0:
            problems.append(f"sensor {sid}: poll_s must be above 0")
    if problems:
        raise ConfigError(f"{path}: " + "; ".join(problems))
    return NodeConfig(name=name, broker_host=host, broker_port=port,
                      outbox_path=Path(outbox.get("path", "outbox.db")).expanduser(),
                      outbox_max=int(outbox.get("max_messages", 100_000)),
                      sensors=sensors, password=env.get("MQTT_PASSWORD") or None)
