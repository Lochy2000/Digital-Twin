"""
Decoder for the FAKE vendor "Borealis".

Borealis's format (a list of readings plus a status block):
    {"site": "site4", "unit": "site4-hvac_01",
     "readings": [{"metric": "temperature", "value": 21.29, "unit": "C", "time": "2026-10-14T20:33:38+01:00"},
                  {"metric": "humidity",    "value": 55.6,  "unit": "%", "time": "2026-10-14T20:33:38+01:00"}],
     "status": {"mode": "COOLING"}}

    readings[]     each one -> RawRecord(field=metric, value, time)
    status.{key}   each one -> RawRecord(field="status.<key>"), using the readings' time
    site, unit     metadata, not readings

This is a made-up test format (testing/vendors/borealis_publisher.py), not a real product.
Its device type: mappings/types/borealis_hvac.ttl
"""
from __future__ import annotations

import json
from datetime import datetime

from . import DecodeError, RawRecord


class BorealisDecoder:
    source = "borealis"

    def decode(self, device: str, payload: bytes, binding=None, kind: str = "") -> list[RawRecord]:
        # binding and kind aren't needed: everything this format needs is in the message.
        try:
            msg = json.loads(payload)
        except (ValueError, UnicodeDecodeError) as e:
            raise DecodeError(f"borealis: payload is not JSON ({e})") from e
        if not isinstance(msg, dict) or not isinstance(msg.get("readings", []), list):
            raise DecodeError("borealis: expected an object with a 'readings' list")

        records: list[RawRecord] = []
        latest: datetime | None = None

        for i, r in enumerate(msg.get("readings", [])):
            try:
                field, value = r["metric"], r["value"]
                time = datetime.fromisoformat(r["time"]) if r.get("time") else None
            except (KeyError, TypeError, ValueError) as e:
                raise DecodeError(f"borealis: reading {i} is malformed ({e})") from e
            if time is not None and time.tzinfo is None:
                raise DecodeError(f"borealis: reading {i} time has no timezone")
            records.append(RawRecord(self.source, device, field, value, time))
            if time is not None and (latest is None or time > latest):
                latest = time

        # The status block has no time of its own, so it borrows the newest reading time.
        for key, value in (msg.get("status") or {}).items():
            records.append(RawRecord(self.source, device, f"status.{key}", value, latest))

        return records
