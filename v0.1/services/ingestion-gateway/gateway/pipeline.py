"""
Pipeline: one raw MQTT message in -> the messages to publish out, plus log lines.

    raw/{source}/{device}/...
        decode -> map -> normalise -> validate
            -> dt/v1/telemetry/{site}/{equipment}/{point}   canonical message (GOOD / SUSPECT / BAD)
            -> dt/v1/quarantine/{source}                    anything that couldn't be turned into one,
                                                            including a message that hit a gateway bug
            (fields the device type marks OPTIONAL and the asset model has no point for are
             counted, not quarantined: see "Known optional fields" below)

This file knows nothing about MQTT connections; it only decides WHAT to publish. That
keeps it testable without a broker. gateway/service.py does the connecting and sending.

Logging (one line per event, key=value "logfmt" style, easy to read and to search):
    INFO     every reading that isn't GOOD, with the validator's reasons
    WARNING  every quarantined message or field, with the reason
    ERROR    a gateway bug (with the stack trace); the message is quarantined (stage=internal)
    DEBUG    every GOOD reading, every skipped optional field (off by default; LOG_LEVEL=DEBUG)

Known optional fields (step 2l): a device type can mark a value optional ("an installed unit may
not have this value", WoT tm:optional). If the asset model has no point for it, the mapper already
reports it once at start-up. Quarantining it on every message as well would fill the quarantine
table with something already known (Acme's humidity: every 3 s). So it is filtered out and
counted (take_skipped(); service.py logs the counts once a minute). This is the EIP Message Filter:
"If the message content does not match the criteria, the message is discarded." Unknown fields,
fields of disabled bindings, and unbound devices still go to quarantine. Add the point to the asset
model and the field is mapped on the next start.

Sources:
  - Topics and QoS:  v0.1/contracts/topics.md
  - Message shapes:  v0.1/contracts/canonical_message.schema.json, quarantine_message.schema.json
  - Quarantine = EIP Invalid Message Channel:
      https://www.enterpriseintegrationpatterns.com/patterns/messaging/InvalidMessageChannel.html
  - Keep the original + add error context (Kafka Connect dead letter queue):
      https://docs.confluent.io/platform/current/installation/configuration/connect/sink-connect-configs.html
  - logfmt:  https://brandur.org/logfmt
  - Message Filter:  https://www.enterpriseintegrationpatterns.com/Filter.html
  - Optional values (tm:optional):  https://www.w3.org/TR/wot-thing-description11/#thing-model
  - A message that makes the code fail goes to the dead letter channel instead of being lost
    (Kafka Connect errors.tolerance + DLQ, link above; EIP Dead Letter Channel):
      https://www.enterpriseintegrationpatterns.com/patterns/messaging/DeadLetterChannel.html
"""
from __future__ import annotations

import json
import logging
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .decoders import DecodeError, RawRecord, decode, parse_raw_topic
from .mapper import Mapper
from .normaliser import NormaliseError, normalise, to_utc_text
from .validator import with_quality

log = logging.getLogger("gateway")

TOPIC_LEVEL = re.compile(r"^[a-z0-9_]+$")       # contracts/topics.md, naming rule 2


@dataclass(frozen=True)
class Outgoing:
    topic: str
    payload: dict
    qos: int = 1               # topics.md: QoS 1 for telemetry and quarantine
    retain: bool = False       # readings are never retained (topics.md)


def kv(event: str, **fields: Any) -> str:
    """logfmt line: kv("quarantine", stage="map", field="rh") -> 'quarantine stage=map field=rh'"""
    parts = [event]
    for key, value in fields.items():
        if value is None:
            continue
        text = value if isinstance(value, str) else json.dumps(value, default=str)
        if text == "" or re.search(r'[\s="]', text):
            text = '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
        parts.append(f"{key}={text}")
    return " ".join(parts)


def telemetry_topic(site: str, point_id: str) -> str:
    """unit1.zone_air_temp -> dt/v1/telemetry/site1/unit1/zone_air_temp  (topics.md, "How a canonical topic is built")"""
    return f"dt/v1/telemetry/{site}/" + point_id.replace(".", "/")


def quarantine_topic(source: str | None) -> str:
    # The source comes from outside, so make sure it's a legal topic level before using it.
    return f"dt/v1/quarantine/{source if source and TOPIC_LEVEL.match(source) else 'unknown'}"


class Pipeline:
    def __init__(self, mapper: Mapper, site: str, **validator_options):
        self.mapper = mapper
        self.site = site
        self.validator_options = validator_options    # e.g. max_age=None for a back-fill
        self.skipped: Counter = Counter()             # (source, device, field) -> how many skipped

    def process(self, topic: str, payload: bytes, now: datetime) -> list[Outgoing]:
        """Never raises: a bug while processing quarantines the whole message (stage=internal)."""
        try:
            return self._process(topic, payload, now)
        except Exception as e:                       # a bug must not lose the message (step 2j)
            log.exception(kv("pipeline_error", topic=topic, error=repr(e)))
            body = {"v": 2, "site": self.site, "stage": "internal",
                    "reason": f"gateway error: {e!r} (see the gateway log; replay once fixed)",
                    "topic": topic, "source": None, "device": None,
                    "raw": payload.decode("utf-8", errors="replace"), "ingest_time": to_utc_text(now)}
            try:
                body["source"], body["device"] = parse_raw_topic(topic)
            except DecodeError:
                pass
            return [Outgoing(quarantine_topic(body["source"]), body)]

    def _process(self, topic: str, payload: bytes, now: datetime) -> list[Outgoing]:
        raw_text = payload.decode("utf-8", errors="replace")
        ingest = to_utc_text(now)

        def quarantine(stage, reason, source=None, device=None, record: RawRecord | None = None) -> Outgoing:
            body = {"v": 2, "site": self.site, "stage": stage, "reason": reason, "topic": topic,
                    "source": source, "device": device, "raw": raw_text, "ingest_time": ingest}
            if record is not None:
                body["field"], body["value"] = record.field, record.value
            log.warning(kv("quarantine", stage=stage, topic=topic,
                           field=record.field if record else None,
                           value=record.value if record else None, reason=reason))
            return Outgoing(quarantine_topic(source), body)

        # 1. Decode the whole message. If that fails, quarantine all of it.
        try:
            source, device = parse_raw_topic(topic)
        except DecodeError as e:
            return [quarantine("decode", str(e))]
        try:
            records = decode(topic, payload, self.mapper)
        except DecodeError as e:
            return [quarantine("decode", str(e), source, device)]

        out: list[Outgoing] = []
        for r in records:
            # 2. Map. Say WHY a field has no point, so the log tells you what to fix.
            mapping = self.mapper.lookup(r.source, r.device, r.field)
            if mapping is None:
                if self._known_optional(r):            # known and deliberately not mapped: count it
                    self.skipped[(r.source, r.device, r.field)] += 1
                    log.debug(kv("optional_field_skipped", source=r.source, device=r.device, field=r.field))
                    continue
                out.append(quarantine("map", self._why_unmapped(r), source, device, r))
                continue

            # 3. Normalise.
            try:
                reading = normalise(r, mapping, now, self.site)
            except NormaliseError as e:
                out.append(quarantine("normalise", str(e), source, device, r))
                continue

            # 4. Validate, then publish whatever the quality. BAD is stored, not dropped,
            #    and the message's qc list says why (message v2).
            message, verdict = with_quality(reading, mapping, **self.validator_options)
            line = kv("reading", point=message["point"], value=message["value"], unit=message["unit"],
                      quality=message["quality"], sensor_time=message["sensor_time"],
                      source=message["source"], reasons="; ".join(verdict.reasons) or None)
            (log.debug if verdict.quality == "GOOD" else log.info)(line)
            out.append(Outgoing(telemetry_topic(self.site, message["point"]), message))
        return out

    def take_skipped(self) -> dict[str, int]:
        """Counts of skipped optional fields since the last call, as {"acme/acme_hvac_0001/rh": 20}; resets."""
        counts = {f"{s}/{d}/{f}": n for (s, d, f), n in sorted(self.skipped.items())}
        self.skipped.clear()
        return counts

    def _known_optional(self, r: RawRecord) -> bool:
        """Optional in the device type, no point in the asset model, and the device is enabled."""
        binding = self.mapper.binding(r.source, r.device)
        return bool(binding and binding.enabled and self.mapper.why_unmapped(r.source, r.device, r.field))

    def _why_unmapped(self, r: RawRecord) -> str:
        binding = self.mapper.binding(r.source, r.device)
        if binding is None:
            return f"device {r.source}/{r.device} is not bound (add it to mappings/bindings/)"
        if not binding.enabled:
            return f"binding for {r.source}/{r.device} is disabled (dtteo:enabled false)"
        why = self.mapper.why_unmapped(r.source, r.device, r.field)
        if why:
            return f"field {r.field!r}: {why} (add the point to the asset model to keep it)"
        return f"field {r.field!r} is not in device type {binding.device_type} (add it to the type)"
