"""
Normaliser: "make every vendor's reading look the same".

Takes one RawRecord (from a decoder) plus its PointMapping (from the mapper) and returns
a reading in our standard form, which is the canonical message minus `quality`:

    in:   tempF = 70.4   @ 19:33:38.428 UTC            (Acme)
          temperature = 21.29 @ 20:33:38+01:00          (Borealis)
    out:  unit1.zone_air_temp = 21.3333 DEG_C @ 2026-10-14T19:33:38.428Z
          unit1.zone_air_temp = 21.29   DEG_C @ 2026-10-14T19:33:38.000Z

Steps, always in this order:
  1. value map      vendor word/code -> our word        "2" -> "cool"
  2. scale          raw number * scale                   2152 * 0.01 -> 21.52
  3. unit           raw unit -> point unit (QUDT)        DEG_F -> DEG_C
  4. tidy number    round off floating-point noise       21.333333333333336 -> 21.3333
  5. times          both times to UTC text ending in Z, and say who set sensor_time
                    (time_source: "device" or "gateway")

It also stamps the site (from gateway config), so site + point identifies the reading
(message v2, step 2i).

If any step can't be done (a word not in the map, text where a number should be, an
unknown unit), it raises NormaliseError and the reading goes to quarantine.

Raw unit: if the message itself states its unit (RawRecord.unit, e.g. Tasmota's "TempUnit"),
that wins over the device type's dtteo:rawUnit, because the device knows its own setting.

What it does NOT do: judge whether a value is sensible (e.g. 999 °C). That's the validator.

Sources:
  - The pattern (many formats in, one common format out):
      EIP Normalizer   https://www.enterpriseintegrationpatterns.com/patterns/messaging/Normalizer.html
  - Unit conversion: see units.py (QUDT)
  - Output shape: v0.1/contracts/canonical_message.schema.json (SenML-like: https://datatracker.ietf.org/doc/rfc8428/)
  - Two times, sensor_time (event time) and ingest_time (processing time):
      https://ci.apache.org/projects/flink/flink-docs-master/docs/concepts/time/
  - No device time = "roughly now" (SenML, RFC 8428 section 4.5.3), recorded as time_source "gateway":
      https://www.rfc-editor.org/rfc/rfc8428
  - site + point as the identity (SenML: base name + name "must result in a globally unique
    identifier", RFC 8428 section 4.2): same link as above
"""
from __future__ import annotations

from datetime import datetime, timezone

from .decoders import RawRecord
from .mapper import PointMapping
from .units import UnitError, convert

DECIMALS = 4   # enough for 0.0001 °C / 0.1 W; only removes float noise, not real precision


class NormaliseError(Exception):
    """The reading can't be put into standard form (-> quarantine with this reason)."""


def to_utc_text(t: datetime) -> str:
    """Any timezone-aware time -> '2026-10-14T19:33:38.428Z' (UTC, milliseconds, Z)."""
    if t.tzinfo is None:
        raise NormaliseError("time has no timezone")      # decoders shouldn't let this through
    return t.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)   # True is an int in Python


def normalise(record: RawRecord, mapping: PointMapping, ingest_time: datetime, site: str) -> dict:
    value = record.value
    raw_unit = record.unit or mapping.raw_unit         # the message's own unit wins (see above)

    # 1. Value map: translate vendor codes/words. Compare as text, so 2 and "2" both match.
    if mapping.value_map is not None:
        key = str(value)
        if key not in mapping.value_map:
            raise NormaliseError(f"value {value!r} is not in the value map for {mapping.point_id}")
        value = mapping.value_map[key]

    # 2 + 3. Numbers: scale, then convert units.
    elif mapping.unit is not None or mapping.scale is not None or raw_unit is not None:
        if not _is_number(value):
            raise NormaliseError(f"expected a number for {mapping.point_id}, got {value!r}")
        if mapping.scale is not None:
            value = float(value) * float(mapping.scale)
        if raw_unit is not None:
            if mapping.unit is None:
                raise NormaliseError(f"{mapping.point_id} has a raw unit but no target unit in the asset model")
            try:
                value = convert(value, raw_unit, mapping.unit)
            except UnitError as e:
                raise NormaliseError(str(e)) from e
        # 4. Tidy: remove floating-point noise. Whole numbers stay as written (int stays int).
        value = round(value, DECIMALS) if isinstance(value, float) else value

    # 5. Times. No device time -> use the time we received it, and say so (time_source).
    from_device = record.time is not None
    sensor_time = record.time if from_device else ingest_time

    return {
        "v": 2,
        "site": site,
        "point": mapping.point_id,
        "value": value,
        "unit": mapping.unit,
        "sensor_time": to_utc_text(sensor_time),
        "ingest_time": to_utc_text(ingest_time),
        "time_source": "device" if from_device else "gateway",
        "source": f"{record.source}:{record.device}",
    }
