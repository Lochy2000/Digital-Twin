"""
Unit conversion using QUDT's own rule.

QUDT gives every unit a conversionMultiplier and conversionOffset that take it to the
SI base unit for its quantity (kelvin for temperature, watt for power, ...):

    value_in_SI   = (value + offset) * multiplier
    value_in_unit = value_in_SI / multiplier - offset

So converting F -> C goes F -> K -> C. Any pair of units of the same quantity works the
same way; no special F-to-C formula is needed.

The table holds only the units v0.1 uses. Values are copied from qudt.org/vocab/unit/<ID>.
Add a row when a new unit appears (and check it against the QUDT page).
"""
from __future__ import annotations

from decimal import Decimal

# QUDT ID: (quantity, conversionMultiplier, conversionOffset)
_UNITS: dict[str, tuple[str, Decimal, Decimal]] = {
    "K":       ("temperature", Decimal("1"),                                  Decimal("0")),
    "DEG_C":   ("temperature", Decimal("1.0"),                                Decimal("273.15")),
    "DEG_F":   ("temperature", Decimal("0.5555555555555555555555555555555556"), Decimal("459.67")),
    "W":       ("power",       Decimal("1"),                                  Decimal("0")),
    "KiloW":   ("power",       Decimal("1000"),                               Decimal("0")),
    "PERCENT": ("dimensionless", Decimal("0.01"),                             Decimal("0")),
}


class UnitError(Exception):
    """Unknown unit, or units that measure different things (e.g. kW -> DEG_C)."""


def convert(value: float, from_unit: str, to_unit: str) -> float:
    if from_unit == to_unit:
        return value
    try:
        q_from, m_from, o_from = _UNITS[from_unit]
        q_to, m_to, o_to = _UNITS[to_unit]
    except KeyError as e:
        raise UnitError(f"unknown unit {e.args[0]!r} (add it to gateway/units.py from qudt.org)") from None
    if q_from != q_to:
        raise UnitError(f"can't convert {from_unit} ({q_from}) to {to_unit} ({q_to})")

    si = (Decimal(str(value)) + o_from) * m_from      # e.g. F -> K
    return float(si / m_to - o_to)                    # e.g. K -> C
