"""
Modbus data types: which xsd types a register value can have, and how many 16-bit
registers each takes. Used by the gateway's Modbus decoder (to unpack) and by the mapper
(to refuse a binding with the wrong register count at start-up).

Moved here from the v0.1 Modbus decoder so the mapper no longer imports gateway code.

Source: W3C WoT Modbus binding (modv:type), https://w3c.github.io/wot-binding-templates/bindings/protocols/modbus/
"""

# xsd type (local name) -> (struct format, registers needed). Big-endian '>' after reordering.
FORMATS = {
    "short": ("h", 1), "unsignedShort": ("H", 1),
    "int": ("i", 2),   "unsignedInt": ("I", 2),   "float": ("f", 2),
    "long": ("q", 4),  "unsignedLong": ("Q", 4),  "double": ("d", 4),
}
