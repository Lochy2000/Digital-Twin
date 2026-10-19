"""
Decoder for Modbus register reads. A REAL protocol (used by the Eastron SDM120 meter, etc.).

Modbus devices don't send messages; something has to ASK them ("poll"). A small poller
(later step) reads the registers listed in the device type and publishes exactly what
it got back, untouched, on  raw/modbus/{device}/registers :

    {"time": "2026-10-18T10:22:00.000Z",
     "registers": {"InputRegister:12": [17551, 53248],     <- 2 x 16-bit words
                   "InputRegister:0":  [17254, 39322]}}

    time       when the poller read them, UTC. Modbus itself carries no timestamps.
    registers  "<register kind>:<address>" -> the 16-bit words read, in wire order

This decoder turns those words into numbers. How, depends on the device type, so it
needs the device's binding (Binding.registers, built from the type's modv: terms):

    modv:type                  xsd:float = 32-bit IEEE 754 float, needs 2 registers
    modv:mostSignificantByte   true = big-endian inside each register (the Modbus default)
    modv:mostSignificantWord   true = first register holds the high half ("no word swap")

Manufacturers differ on both, so there are four possible orders. Getting it wrong gives
nonsense numbers, which is why it is stated in the type, never assumed.

Keeping the poller dumb (raw words out) and the decoding here means the raw topic
shows exactly what the device said, and decoding can be tested without a device.

Sources:
  - Terms and their meaning (modv:type, mostSignificantByte/Word, entity, address, quantity):
      W3C WoT Modbus binding   https://w3c.github.io/wot-binding-templates/bindings/protocols/modbus/index.html
  - SDM120 registers are FLOAT32, big-endian byte and word order (sdm-modbus 0.4.3 source):
      https://pypi.org/project/sdm-modbus/0.4.3/
  - Unpacking bytes into numbers:   https://docs.python.org/3.9/library/struct.html
Device type: mappings/types/eastron_sdm120.ttl
"""
from __future__ import annotations

import json
import struct
from datetime import datetime

from . import DecodeError, RawRecord

# xsd type (local name) -> (struct format, registers needed). Big-endian '>' after reordering.
FORMATS = {
    "short": ("h", 1), "unsignedShort": ("H", 1),
    "int": ("i", 2),   "unsignedInt": ("I", 2),   "float": ("f", 2),
    "long": ("q", 4),  "unsignedLong": ("Q", 4),  "double": ("d", 4),
}


def unpack(words: list[int], xsd_type: str, msb_first: bool = True, msw_first: bool = True):
    """
    16-bit register words -> one number.

    >>> unpack([0x448F, 0xD000], "float")          # 0x448FD000 = 1150.5
    1150.5
    """
    if xsd_type not in FORMATS:
        raise DecodeError(f"modbus: data type xsd:{xsd_type} not supported yet")
    fmt, needed = FORMATS[xsd_type]
    if len(words) != needed:
        raise DecodeError(f"modbus: xsd:{xsd_type} needs {needed} register(s), got {len(words)}")
    if any(not isinstance(w, int) or isinstance(w, bool) or not 0 <= w <= 0xFFFF for w in words):
        raise DecodeError(f"modbus: register values must be 0..65535, got {words}")

    ordered = words if msw_first else list(reversed(words))         # undo word swap
    data = b"".join(w.to_bytes(2, "big" if msb_first else "little") for w in ordered)  # undo byte swap
    value = struct.unpack(">" + fmt, data)[0]
    return value


class ModbusDecoder:
    source = "modbus"

    def decode(self, device: str, payload: bytes, binding=None, kind: str = "") -> list[RawRecord]:
        try:
            msg = json.loads(payload)
            time = datetime.fromisoformat(msg["time"].replace("Z", "+00:00"))
            registers = msg["registers"]
        except (ValueError, UnicodeDecodeError, KeyError, TypeError, AttributeError) as e:
            raise DecodeError(f"modbus: expected {{'time': ..., 'registers': {{...}}}} ({e})") from e
        if time.tzinfo is None:
            raise DecodeError("modbus: poller time has no timezone (it should end in Z)")
        if not isinstance(registers, dict):
            raise DecodeError("modbus: 'registers' must be an object")
        if binding is None:
            # Without the device type we can't know how to read the words.
            raise DecodeError(f"modbus: device {device!r} has no binding, so its registers can't be decoded")

        records = []
        for field, words in registers.items():
            spec = binding.registers.get(field)
            if spec is None:
                # A register the type doesn't describe: keep the raw words so nothing is lost.
                records.append(RawRecord(self.source, device, field, words, time))
                continue
            if not isinstance(words, list):
                raise DecodeError(f"modbus: {field} should be a list of register values")
            value = unpack(words, spec.xsd_type, spec.msb_first, spec.msw_first)
            records.append(RawRecord(self.source, device, field, value, time))
        return records
