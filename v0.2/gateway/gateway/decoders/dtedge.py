"""
Decoder for dt-edge, Botanic's own rig software (the dt-edge repo, on the Pi).

Topic:  raw/dtedge/{node}/telemetry      node = the Pi that sends, e.g. digitwin_pi

Payload: one dt-edge reading, or a list of them (one poll of several sensors):
    {"v": 2, "site": "rig1", "point_id": "tc08.ch1", "value": 21.4, "unit": "DEG_C",
     "sensor_time": "2026-11-08T21:00:00.123456+00:00", "ingest_time": "...",
     "quality": "GOOD", "qc": null, "time_source": "device", "source": "tc08:tc08"}

This is dt-edge's Reading.to_message() (dt-edge app/record.py). It LOOKS like our canonical
message but isn't one, so it is decoded like any other device format:
    point_id   is dt-edge's own name (sensor id + metric) -> becomes the FIELD; the binding
               says which asset-model point it is (model/mappings/bindings/rig.ttl)
    site       ignored: the gateway stamps its own site
    unit       passed on (the normaliser converts if the point uses another unit)
    quality/qc passed on as the device's own verdict (validator check "device_flag")
    sensor_time  must carry a UTC offset; times are converted to UTC later
    value null   passed on; the normaliser quarantines it ("no value")

Device type: model/mappings/types/dtedge_rig.ttl
"""
from __future__ import annotations

import json
from datetime import datetime

from . import DecodeError, RawRecord

VERSION = 2                     # dt-edge's SCHEMA_VERSION; anything else is refused


class DtEdgeDecoder:
    source = "dtedge"

    def decode(self, device: str, payload: bytes, binding=None, kind: str = "") -> list[RawRecord]:
        try:
            data = json.loads(payload)
        except (ValueError, UnicodeDecodeError) as e:
            raise DecodeError(f"dtedge: not JSON ({e})") from e
        items = data if isinstance(data, list) else [data]
        if not items:
            raise DecodeError("dtedge: empty list")
        return [self._one(device, m, i) for i, m in enumerate(items)]

    def _one(self, device: str, m, i: int) -> RawRecord:
        where = f"dtedge reading {i}"
        if not isinstance(m, dict):
            raise DecodeError(f"{where}: expected an object, got {type(m).__name__}")
        if m.get("v") != VERSION:
            raise DecodeError(f"{where}: version {m.get('v')!r}, this decoder reads v{VERSION}")
        point = m.get("point_id")
        if not isinstance(point, str) or not point:
            raise DecodeError(f"{where}: no point_id")
        if "value" not in m:
            raise DecodeError(f"{where} ({point}): no value key")
        try:
            t = datetime.fromisoformat(str(m.get("sensor_time")).replace("Z", "+00:00"))
        except ValueError as e:
            raise DecodeError(f"{where} ({point}): sensor_time {m.get('sensor_time')!r} is not a time") from e
        if t.tzinfo is None:
            raise DecodeError(f"{where} ({point}): sensor_time has no UTC offset")
        quality = m.get("quality")
        if quality not in (None, "GOOD", "SUSPECT", "BAD"):
            raise DecodeError(f"{where} ({point}): unknown quality {quality!r}")
        qc = m.get("qc") or ()
        return RawRecord(source=self.source, device=device, field=point, value=m["value"], time=t,
                         unit=m.get("unit") or None, device_quality=quality,
                         device_qc=tuple(str(x) for x in qc) if isinstance(qc, list) else (str(qc),))
