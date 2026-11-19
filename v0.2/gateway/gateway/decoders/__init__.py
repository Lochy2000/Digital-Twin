"""
Decoders: "what does this device's message say?"

One decoder per message FORMAT. Each turns a raw message into a list of RawRecords:
plain (field, value, time) triples that the mapper can look up.

Rules every decoder follows:
  - Understand the format's SYNTAX only: its layout, its field names, its time format,
    how numbers are packed into bytes (Modbus).
  - Emit EVERY data field it finds. Don't filter. The mapper decides what's known;
    anything unknown goes to quarantine. A new field from a device never gets silently lost.
  - Don't convert units or translate values (F->C, 2->"cool"). That's the normaliser's job.
    If the MESSAGE says what unit it is in (Tasmota's "TempUnit"), pass that on in
    RawRecord.unit; the normaliser uses it.
  - If the message can't be understood at all, raise DecodeError (the whole message is quarantined).

Some formats need facts about the installed device that aren't in the message, e.g.
Tasmota's timezone or a Modbus meter's register layout. Those come from the device's
binding (mappings/bindings/), looked up through the `registry` passed to decode().

Adding a real format = add a module here + list it in DECODERS below + a device type in
model/mappings/types/. A test-only format goes in a plug-in folder instead (load_plugins).

Sources:
  - Pattern (one adapter per protocol/format, separate from the rest of the platform):
    Eclipse Hono component view   https://eclipse.dev/hono/docs/architecture/component-view/
  - Unknown data goes to its own channel, never dropped:
    EIP Invalid Message Channel   https://www.enterpriseintegrationpatterns.com/patterns/messaging/InvalidMessageChannel.html
  - Topic layout raw/{source}/{device}/...:   v0.1/contracts/topics.md
"""
from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class RawRecord:
    source: str                    # format / adapter, e.g. "acme"         (from the topic)
    device: str                    # device slug, e.g. "acme_hvac_0001"    (from the topic)
    field: str                     # the format's field name, e.g. "tempF" or "status.mode"
    value: Any                     # as sent (Modbus: as unpacked from the registers)
    time: datetime | None          # when measured, timezone-aware; None if the device gave no time
    unit: str | None = None        # QUDT unit IF the message itself states it, e.g. "DEG_F"
    # What the DEVICE said about its own reading, if its format has that (dt-edge does).
    # The validator turns it into one more check; the gateway still runs all its own checks.
    device_quality: str | None = None          # "GOOD" / "SUSPECT" / "BAD"
    device_qc: tuple[str, ...] = ()            # the device's reasons, e.g. ("bad_pixels",)


class DecodeError(Exception):
    """The message couldn't be understood at all (not JSON, missing required parts, ...)."""


class Decoder(Protocol):
    """Anything with a `source` name and a `decode` method counts as a decoder."""
    source: str

    def decode(self, device: str, payload: bytes, binding=None, kind: str = "") -> list[RawRecord]:
        """binding: the device's Binding (or None); kind: the rest of the topic, e.g. "tele/SENSOR"."""
        ...


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


def topic_kind(topic: str) -> str:
    """The part after raw/{source}/{device}/, e.g. "tele/SENSOR". Empty if there is none."""
    return "/".join(topic.split("/")[3:])


# --- Registry: which decoder handles which source -----------------------------------
# Built-in decoders are the real formats only. Test and dev formats (the fake Acme and
# Borealis vendors) are added as plug-ins with load_plugins(), so they never sit in the
# live table by accident (v0.2 change 7).
from .dtedge import DtEdgeDecoder      # noqa: E402  (imported here to avoid a circular import)
from .modbus import ModbusDecoder      # noqa: E402
from .tasmota import TasmotaDecoder    # noqa: E402

DECODERS: dict[str, Decoder] = {d.source: d for d in (TasmotaDecoder(), ModbusDecoder(), DtEdgeDecoder())}


def register(decoder: Decoder) -> None:
    """Add a decoder to the table. Loading the same plug-in again is fine; a DIFFERENT decoder
    for a source that already has one is refused (two formats can't share raw/{source}/...)."""
    def identity(d):
        return type(d).__module__, type(d).__qualname__
    existing = DECODERS.get(decoder.source)
    if existing is not None and identity(existing) != identity(decoder):
        raise ValueError(f"a decoder for source {decoder.source!r} is already registered")
    DECODERS[decoder.source] = decoder


def load_plugins(folder: Path) -> list[str]:
    """
    Register every decoder in folder/decoders/*.py. Each file must define DECODER = SomeDecoder().
    Returns the sources added, e.g. ["acme", "borealis"]. Missing folder -> nothing added.

    Plug-in pattern: the files are loaded by path (importlib), so a plug-in folder can live
    anywhere (tests/vendors/ in the tests, a mounted folder in the dev setup).
    Source: https://docs.python.org/3/library/importlib.html#importing-a-source-file-directly
    """
    added = []
    for path in sorted((Path(folder) / "decoders").glob("*.py")):
        spec = importlib.util.spec_from_file_location(f"gateway_plugin_{path.stem}", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        decoder = getattr(module, "DECODER", None)
        if decoder is None:
            raise ValueError(f"plug-in {path} has no DECODER = ... at the bottom")
        register(decoder)
        added.append(decoder.source)
    return added


def decode(topic: str, payload: bytes, registry=None) -> list[RawRecord]:
    """
    Pick the right decoder from the topic, then decode. Raises DecodeError if nothing fits.

    registry: anything with .binding(source, device), normally the Mapper. It plays the
              role of Hono's device registry: "what do we know about this device?"
    """
    source, device = parse_raw_topic(topic)
    decoder = DECODERS.get(source)
    if decoder is None:
        raise DecodeError(f"no decoder for source {source!r}")
    binding = registry.binding(source, device) if registry is not None else None
    return decoder.decode(device, payload, binding, topic_kind(topic))
