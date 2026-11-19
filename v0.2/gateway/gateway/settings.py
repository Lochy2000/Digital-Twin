"""
Every gateway setting, read and checked ONCE at start-up (v0.2 change 9).

    settings = Settings.from_env()      # raises SettingsError listing EVERY problem at once

Before v0.2 each setting was read with os.getenv where it was used, so a typo (a port of
"188e", a model folder that doesn't exist) only showed up when that line ran, sometimes
long after start-up. Now the gateway refuses to start and says what to fix, all in one go.

Settings (environment variables, as set in gateway/compose.yml):
    BROKER_HOST       default localhost
    BROKER_PORT       default 1883
    GATEWAY_SITE      default site1   (the {site} level in canonical topics; topics.md)
    MODEL_DIR         folder with dtteo_asset_model.ttl and mappings/  (default: gateway/model)
    GATEWAY_PLUGINS   optional folder of plug-ins: decoders/*.py and mappings/**/*.ttl
    GATEWAY_ENABLED   optional on/off overrides for bindings, e.g. "acme_hvac_0001=off,site4_hvac_01=on"
    LOG_LEVEL         default INFO  (DEBUG also logs every GOOD reading)
    MQTT_USERNAME     default ingestion_gateway;  MQTT_PASSWORD its password (none = anonymous)

Pattern: configuration from the environment ("Twelve-Factor App", III. Config,
https://12factor.net/config), checked at start-up so the service fails fast.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

DEFAULT_MODEL_DIR = Path(__file__).resolve().parents[1] / "model"
TOPIC_LEVEL = re.compile(r"^[a-z0-9_]+$")          # contracts/topics.md, naming rule 2
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")


class SettingsError(ValueError):
    """One or more settings are wrong. The message lists all of them."""


def parse_enabled(text: str) -> dict[str, bool]:
    """'acme_hvac_0001=off,site4_hvac_01=on' -> {'acme_hvac_0001': False, 'site4_hvac_01': True}"""
    out = {}
    for item in filter(None, (part.strip() for part in text.split(","))):
        device, _, state = item.partition("=")
        if state.strip().lower() not in ("on", "off"):
            raise ValueError(f"GATEWAY_ENABLED: expected device=on|off, got {item!r}")
        out[device.strip()] = state.strip().lower() == "on"
    return out


@dataclass(frozen=True)
class Settings:
    broker_host: str = "localhost"
    broker_port: int = 1883
    site: str = "site1"
    model_dir: Path = DEFAULT_MODEL_DIR
    plugins: Path | None = None
    enabled: dict[str, bool] = field(default_factory=dict)
    log_level: str = "INFO"
    mqtt_username: str = "ingestion_gateway"
    mqtt_password: str | None = field(default=None, repr=False)     # never printed

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> "Settings":
        problems: list[str] = []

        def get(name: str) -> str | None:
            value = env.get(name, "").strip()
            return value or None

        port = cls.broker_port
        if get("BROKER_PORT"):
            try:
                port = int(get("BROKER_PORT"))
                if not 1 <= port <= 65535:
                    raise ValueError
            except ValueError:
                problems.append(f"BROKER_PORT must be a number from 1 to 65535, got {get('BROKER_PORT')!r}")

        site = get("GATEWAY_SITE") or cls.site
        if not TOPIC_LEVEL.match(site):
            problems.append(f"GATEWAY_SITE must be lowercase letters, digits and _ (it's a topic level), got {site!r}")

        model_dir = Path(get("MODEL_DIR")) if get("MODEL_DIR") else DEFAULT_MODEL_DIR
        if not (model_dir / "dtteo_asset_model.ttl").is_file():
            problems.append(f"MODEL_DIR {str(model_dir)!r} has no dtteo_asset_model.ttl")

        plugins = Path(get("GATEWAY_PLUGINS")) if get("GATEWAY_PLUGINS") else None
        if plugins is not None and not plugins.is_dir():
            problems.append(f"GATEWAY_PLUGINS {str(plugins)!r} is not a folder")

        enabled = {}
        try:
            enabled = parse_enabled(get("GATEWAY_ENABLED") or "")
        except ValueError as e:
            problems.append(str(e))

        level = (get("LOG_LEVEL") or cls.log_level).upper()
        if level not in LOG_LEVELS:
            problems.append(f"LOG_LEVEL must be one of {', '.join(LOG_LEVELS)}, got {level!r}")

        if problems:
            raise SettingsError("gateway settings: " + "; ".join(problems))
        return cls(broker_host=get("BROKER_HOST") or cls.broker_host, broker_port=port, site=site,
                   model_dir=model_dir, plugins=plugins, enabled=enabled, log_level=level,
                   mqtt_username=get("MQTT_USERNAME") or cls.mqtt_username, mqtt_password=get("MQTT_PASSWORD"))

    def for_log(self) -> dict:
        """The settings as they will be logged at start-up: everything except the password."""
        return {"broker": f"{self.broker_host}:{self.broker_port}", "site": self.site,
                "model_dir": str(self.model_dir), "plugins": str(self.plugins) if self.plugins else None,
                "enabled_overrides": self.enabled or None, "log_level": self.log_level,
                "mqtt_username": self.mqtt_username, "mqtt_password_set": self.mqtt_password is not None}

