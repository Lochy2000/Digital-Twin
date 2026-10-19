"""
Decoder for the FAKE vendor "Acme".

Acme's format (one flat JSON object per message):
    {"deviceId": "ACME-HVAC-0001", "ts": 1792006418428, "tempF": 70.4, "rh": 54.0, "op_state": 2}

    ts        epoch MILLISECONDS (UTC)        -> becomes the time of every record
    deviceId  Acme's own ID                    -> metadata, not a reading
    all other keys are readings                -> one RawRecord each

This is a made-up test format (testing/vendors/acme_publisher.py), not a real product.
Its device type: mappings/types/acme_hvac.ttl
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from . import DecodeError, RawRecord

METADATA_KEYS = {"deviceId", "ts"}   # everything else is treated as a reading


class AcmeDecoder:
    source = "acme"

    def decode(self, device: str, payload: bytes, binding=None, kind: str = "") -> list[RawRecord]:
        # binding and kind aren't needed: everything this format needs is in the message.
        try:
            msg = json.loads(payload)
        except (ValueError, UnicodeDecodeError) as e:
            raise DecodeError(f"acme: payload is not JSON ({e})") from e
        if not isinstance(msg, dict):
            raise DecodeError("acme: expected a JSON object")

        time = None
        if "ts" in msg:
            try:
                time = datetime.fromtimestamp(msg["ts"] / 1000, tz=timezone.utc)
            except (TypeError, ValueError, OverflowError) as e:
                raise DecodeError(f"acme: bad ts {msg['ts']!r}") from e

        return [
            RawRecord(self.source, device, field, value, time)
            for field, value in msg.items()
            if field not in METADATA_KEYS
        ]
