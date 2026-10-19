"""
Decoder for Tasmota, open-source firmware for ESP8266/ESP32 boards. A REAL format.

What Tasmota sends (DS18B20 probe example, from the Tasmota docs):
    {"Time":"2021-01-02T09:09:44","DS18B20":{"Id":"00000566CC39","Temperature":13.3},"TempUnit":"C"}

Topics. By default Tasmota publishes on  tele/<topic>/SENSOR  (and STATE, LWT).
Our gateway expects raw/{source}/{device}/..., so the device is set up with two Tasmota
commands (no firmware change):
    Topic      tasmota_zone1
    FullTopic  raw/tasmota/%topic%/%prefix%/
which makes it publish on  raw/tasmota/tasmota_zone1/tele/SENSOR.

What this decoder does:
    nested JSON          flattened with dots:      DS18B20.Temperature = 13.3
    Time, TempUnit, *.Id metadata, not readings
    "TempUnit"           passed on as RawRecord.unit for every *Temperature field
                         (SetOption8 switches Tasmota between C and F)
    Time                 local time with NO offset by default. Turned into a real time
                         using the binding's timezone. If SetOption52 is on, Tasmota adds
                         the offset itself and that is used instead.
    tele/LWT             plain text "Online" / "Offline" -> one record, field "LWT"
    tele/STATE           device health (uptime, Wi-Fi...) -> flattened like SENSOR;
                         nothing maps it yet, so it is quarantined, not lost

Sources:
  - Message example:           https://tasmota.github.io/docs/DS18x20/
  - Topics, LWT, TelePeriod:   https://tasmota.github.io/docs/MQTT/
  - Topic, FullTopic, SetOption8 (C/F), SetOption52 (UTC offset in JSON):
                               https://tasmota.github.io/docs/Commands/
  - Ambiguous local times (fold) and tzdata on Windows:
                               https://github.com/python/cpython/blob/main/Doc/library/zoneinfo.rst
Device type: mappings/types/tasmota_ds18b20.ttl
"""
from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import DecodeError, RawRecord

METADATA_KEYS = {"Time", "TempUnit"}
TEMP_UNITS = {"C": "DEG_C", "F": "DEG_F"}       # Tasmota's letters -> QUDT IDs


def _flatten(obj: dict, prefix: str = ""):
    """{"DS18B20": {"Temperature": 13.3}} -> ("DS18B20.Temperature", 13.3)"""
    for key, value in obj.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict):
            yield from _flatten(value, name + ".")
        else:
            yield name, value


def local_to_aware(text: str, tz_name: str | None) -> datetime:
    """
    Tasmota's "Time" -> a timezone-aware datetime.

    With an offset (SetOption52 on), it's already exact. Without one, it's local time
    and we need the device's timezone from its binding. Never guess (step 2c rule).
    """
    t = datetime.fromisoformat(text)
    if t.tzinfo is not None:
        return t
    if not tz_name:
        raise DecodeError("tasmota: time has no offset and the binding gives no dtteo:timezone "
                          "(add one, or turn on SetOption52 on the device)")
    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError as e:
        raise DecodeError(f"tasmota: unknown timezone {tz_name!r} (on Windows: pip install tzdata)") from e

    # When clocks go back, one local hour happens twice (e.g. 01:30 in late October in the UK).
    # fold=0 and fold=1 then give different offsets, and the text alone can't tell which.
    first, second = t.replace(tzinfo=tz, fold=0), t.replace(tzinfo=tz, fold=1)
    if first.utcoffset() != second.utcoffset():
        raise DecodeError(f"tasmota: local time {text} happens twice (clocks went back); "
                          "can't tell which. SetOption52 on the device avoids this")
    return first


class TasmotaDecoder:
    source = "tasmota"

    def decode(self, device: str, payload: bytes, binding=None, kind: str = "") -> list[RawRecord]:
        # Last Will: plain text, not JSON.
        if kind.endswith("LWT"):
            return [RawRecord(self.source, device, "LWT", payload.decode("utf-8", "replace").strip(), None)]

        try:
            msg = json.loads(payload)
        except (ValueError, UnicodeDecodeError) as e:
            raise DecodeError(f"tasmota: payload is not JSON ({e})") from e
        if not isinstance(msg, dict):
            raise DecodeError("tasmota: expected a JSON object")

        time = None
        if msg.get("Time"):
            try:
                time = local_to_aware(msg["Time"], binding.timezone if binding else None)
            except (TypeError, ValueError) as e:
                raise DecodeError(f"tasmota: bad Time {msg['Time']!r}") from e

        temp_unit = None
        if "TempUnit" in msg:
            if msg["TempUnit"] not in TEMP_UNITS:
                raise DecodeError(f"tasmota: unknown TempUnit {msg['TempUnit']!r}")
            temp_unit = TEMP_UNITS[msg["TempUnit"]]

        records = []
        for field, value in _flatten({k: v for k, v in msg.items() if k not in METADATA_KEYS}):
            if field.endswith(".Id"):
                continue                                  # the probe's serial number: metadata
            unit = temp_unit if field.endswith("Temperature") else None
            records.append(RawRecord(self.source, device, field, value, time, unit))
        return records
