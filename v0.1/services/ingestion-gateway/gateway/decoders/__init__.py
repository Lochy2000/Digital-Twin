"""
Decoders: "what does this vendor's message say?"

One decoder per vendor FORMAT. Each turns a raw message into a list of RawRecords:
plain (field, value, time) triples that the mapper can look up.

Rules every decoder follows:
  - Understand the vendor's SYNTAX only: its layout, its field names, its time format.
  - Emit EVERY data field it finds. Don't filter. The mapper decides what's known;
    anything unknown goes to quarantine. A new field from a vendor never gets silently lost.
  - Don't convert units or translate values (F->C, 2->"cool"). That's the normaliser's job.
  - If the message can't be understood at all, raise DecodeError (the whole message is quarantined).

Adding a vendor = add a module here + register it in DECODERS below + add a mappings/<vendor>.ttl.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True)
class RawRecord:
    source: str                    # vendor / adapter, e.g. "acme"         (from the topic)
    device: str                    # device slug, e.g. "acme_hvac_0001"    (from the topic)
    field: str                     # vendor's field name, e.g. "tempF" or "status.mode"
    value: Any                     # exactly as sent: 70.4, 2, "COOLING", ...
    time: datetime | None          # when measured, timezone-aware; None if the vendor gave no time


class DecodeError(Exception):
    """The message couldn't be understood at all (not JSON, missing required parts, ...)."""


class Decoder(Protocol):
    """Anything with a `source` name and a `decode` method counts as a decoder."""
    source: str

    def decode(self, device: str, payload: bytes) -> list[RawRecord]: ...


def parse_raw_topic(topic: str) -> tuple[str, str]:
    """
    raw/{source}/{device}/...  ->  (source, device)

    >>> parse_raw_topic("raw/acme/acme_hvac_0001/telemetry")
    ('acme', 'acme_hvac_0001')
    """
    parts = topic.split("/")
    if len(parts) < 3 or parts[0] != "raw" or not parts[1] or not parts[2]:
        raise DecodeError(f"not a raw topic: {topic!r} (expected raw/<source>/<device>/...)")
    return parts[1], parts[2]


# --- Registry: which decoder handles which source -----------------------------------
from .acme import AcmeDecoder          # noqa: E402  (imported here to avoid a circular import)
from .borealis import BorealisDecoder  # noqa: E402

DECODERS: dict[str, Decoder] = {d.source: d for d in (AcmeDecoder(), BorealisDecoder())}


def decode(topic: str, payload: bytes) -> list[RawRecord]:
    """Pick the right decoder from the topic, then decode. Raises DecodeError if nothing fits."""
    source, device = parse_raw_topic(topic)
    decoder = DECODERS.get(source)
    if decoder is None:
        raise DecodeError(f"no decoder for source {source!r}")
    return decoder.decode(device, payload)
