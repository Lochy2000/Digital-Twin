"""
Mapper: "which point is this?"

Answers one question for the rest of the gateway:

    (source, device, field)  ->  point ID + unit info      e.g.
    ("acme", "acme_hvac_0001", "tempF")  ->  unit1.zone_air_temp, DEG_C (raw DEG_F)

It reads Turtle files, all loaded into ONE graph:
  - the asset model (dtteo_asset_model.ttl): what each point IS, its unit, its point ID
  - mappings/types/*.ttl     device types: what each model of device sends (written once per model)
  - mappings/bindings/*.ttl  device bindings: which installed device is which type, serving what
  - mappings/*.ttl           vocabulary, plus optional per-field references for irregular
                             sources such as a BMS export (the step 2b mechanism, still supported)

From these it builds a plain lookup table once, at start-up. Per message, a lookup is a
dictionary read. Anything inconsistent raises MappingError at start-up, never per message.

If a lookup returns None, the field is unknown and the reading goes to quarantine.
Design: v0.1/mappings/DESIGN.md

Sources (what each part follows):
  - Points link to their stored time series with ref:hasExternalReference / ref:TimeseriesReference:
      https://docs.brickschema.org/metadata/timeseries-storage.html
      https://docs.brickschema.org/metadata/external-representations.html
  - brick:hasPoint and brick:feeds, used to find a point on the served equipment:
      https://docs.brickschema.org/brick/relationships.html
  - Device type vs instance (W3C WoT Thing Model, TD 1.1 section 9):
      https://www.w3.org/TR/wot-thing-description11/#thing-model
  - Modbus register terms (modv:entity, modv:address, ...):
      https://w3c.github.io/wot-binding-templates/bindings/protocols/modbus/index.html
  - One data stream per property (rule 3):
      https://docs.aws.amazon.com/iot-sitewise/latest/userguide/data-streams.html
  - SPARQL in rdflib, including initBindings (used in _CANDIDATES):
      https://rdflib.readthedocs.io/en/latest/intro_to_sparql/
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Iterable

from rdflib import Graph
from rdflib.namespace import RDF

log = logging.getLogger(__name__)

BRICK = "https://brickschema.org/schema/Brick#"


@dataclass(frozen=True)
class PointMapping:
    point_id: str             # canonical ID, e.g. "unit1.zone_air_temp"
    unit: str | None          # point's unit (QUDT local name), e.g. "DEG_C"; None if unitless
    raw_unit: str | None      # unit the device sends in, if different, e.g. "DEG_F"
    scale: Decimal | None     # multiply raw number by this first, e.g. 0.1
    value_map: dict[str, str] | None = None   # device value -> our value, e.g. {"2": "cool"}


@dataclass(frozen=True)
class RegisterSpec:
    """How to read one Modbus value. Terms from the W3C WoT Modbus binding (modv:)."""
    entity: str               # "InputRegister", "HoldingRegister", ...
    address: int              # as sent on the wire (0-based)
    quantity: int             # number of 16-bit registers
    xsd_type: str             # "float", "unsignedShort", ...
    msb_first: bool = True    # modv:mostSignificantByte (default true in the spec)
    msw_first: bool = True    # modv:mostSignificantWord (default true in the spec)


@dataclass(frozen=True)
class Binding:
    """One installed device. Holds the instance details decoders / pollers will need later."""
    source: str               # decoder name, e.g. "tasmota" (comes from the device type)
    device: str               # device slug, e.g. "tasmota_zone1"
    device_type: str          # e.g. "tasmota_ds18b20"
    serves: str               # e.g. "zone1"
    enabled: bool
    timezone: str | None      # for devices that send local time with no offset
    base: str | None          # for polled devices, e.g. "modbus+tcp://192.168.1.50:502/1"
    registers: dict = field(default_factory=dict, hash=False)   # Modbus only: field -> RegisterSpec


class MappingError(Exception):
    """The model or mapping files are inconsistent. Raised at start-up, never per message."""


# --- Queries ------------------------------------------------------------------------

_PREFIXES = """
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX ref:   <https://brickschema.org/schema/Brick/ref#>
PREFIX dtteo: <urn:dtteo:schema#>
PREFIX modv:  <https://www.w3.org/2019/wot/modbus#>
"""

# Every point that can be stored: it has a time-series ID. Unit is optional.
_POINTS = _PREFIXES + """
SELECT ?point ?point_id ?unit WHERE {
    ?point ref:hasExternalReference ?ts .
    ?ts a ref:TimeseriesReference ; ref:hasTimeseriesId ?point_id .
    OPTIONAL { ?point brick:hasUnit ?unit }
}"""

# Route 1 (step 2b): a point says directly "I am field Z of device Y from source X".
_FIELD_REFS = _PREFIXES + """
SELECT ?raw ?point ?source ?device ?field ?raw_unit ?scale WHERE {
    ?point ref:hasExternalReference ?raw .
    ?raw a dtteo:RawFieldReference ;
         dtteo:source ?source ; dtteo:device ?device ; dtteo:field ?field .
    OPTIONAL { ?raw dtteo:rawUnit ?raw_unit }
    OPTIONAL { ?raw dtteo:scale   ?scale }
}"""

# Value maps hang off either a field reference or a device type's value.
_VALUE_MAPS = _PREFIXES + """
SELECT ?owner ?from ?to WHERE {
    ?owner dtteo:valueMap ?pair .
    ?pair dtteo:from ?from ; dtteo:to ?to .
}"""

_TYPES = _PREFIXES + """
SELECT ?type ?decoder WHERE { ?type a dtteo:DeviceType . OPTIONAL { ?type dtteo:decoder ?decoder } }"""

_TYPE_VALUES = _PREFIXES + """
SELECT ?type ?v ?field ?cls ?raw_unit ?scale ?optional ?entity ?address ?quantity ?xsd ?msb ?msw WHERE {
    ?type a dtteo:DeviceType ; dtteo:hasValue ?v .
    OPTIONAL { ?v dtteo:field ?field }
    OPTIONAL { ?v dtteo:pointClass ?cls }
    OPTIONAL { ?v dtteo:rawUnit ?raw_unit }
    OPTIONAL { ?v dtteo:scale ?scale }
    OPTIONAL { ?v dtteo:optional ?optional }
    OPTIONAL { ?v modv:entity ?entity }
    OPTIONAL { ?v modv:address ?address }
    OPTIONAL { ?v modv:quantity ?quantity }
    OPTIONAL { ?v modv:type ?xsd }
    OPTIONAL { ?v modv:mostSignificantByte ?msb }
    OPTIONAL { ?v modv:mostSignificantWord ?msw }
}"""

_BINDINGS = _PREFIXES + """
SELECT ?b ?device ?type ?serves ?enabled ?tz ?base WHERE {
    ?b a dtteo:DeviceBinding .
    OPTIONAL { ?b dtteo:device ?device }
    OPTIONAL { ?b dtteo:deviceType ?type }
    OPTIONAL { ?b dtteo:serves ?serves }
    OPTIONAL { ?b dtteo:enabled ?enabled }
    OPTIONAL { ?b dtteo:timezone ?tz }
    OPTIONAL { ?b dtteo:base ?base }
}"""

_PLACES = _PREFIXES + """
SELECT ?b ?field ?point WHERE { ?b dtteo:place [ dtteo:field ?field ; dtteo:point ?point ] }"""

# Points of a given Brick class on the served entity, or on what it feeds
# (a heat pump feeds zone 1, so zone 1's air temperature point counts).
_CANDIDATES = _PREFIXES + """
SELECT DISTINCT ?point WHERE {
    { ?serves brick:hasPoint ?point } UNION { ?serves brick:feeds/brick:hasPoint ?point }
    ?point a ?cls .
}"""


def _local_name(uri) -> str | None:
    """http://qudt.org/vocab/unit/DEG_C  ->  DEG_C"""
    if uri is None:
        return None
    return str(uri).rstrip("/").rsplit("/", 1)[-1].rsplit("#", 1)[-1]


def _short(uri) -> str:
    """For messages: brick:Mode_Status rather than the full IRI."""
    s = str(uri)
    return "brick:" + s[len(BRICK):] if s.startswith(BRICK) else (_local_name(s) or s)


def mapping_files(v01: Path) -> list[Path]:
    """Every .ttl under v0.1/mappings (types/ and bindings/ included), sorted. Same on Windows."""
    return sorted((v01 / "mappings").rglob("*.ttl"))


class Mapper:
    def __init__(self, table: dict[tuple[str, str, str], PointMapping],
                 bindings: dict[tuple[str, str], Binding] | None = None,
                 report: list[str] | None = None):
        self._table = table
        self._bindings = bindings or {}
        self.report = report or []      # notes for people: skipped optional values, disabled devices

    @classmethod
    def from_files(cls, asset_model: Path, mapping_files: Iterable[Path],
                   enabled: dict[str, bool] | None = None) -> "Mapper":
        """
        enabled: optional override of the bindings' on/off switch, by device slug,
                 e.g. {"acme_hvac_0001": False, "site4_hvac_01": True}.
                 Lets tests and the demo swap vendors without editing files.
        """
        graph = Graph()
        graph.parse(asset_model, format="turtle")
        for path in mapping_files:
            graph.parse(path, format="turtle")
        return _Builder(graph, enabled or {}).build()

    @classmethod
    def from_folder(cls, v01: Path, enabled: dict[str, bool] | None = None) -> "Mapper":
        """The usual set: v0.1's asset model + every .ttl under mappings/."""
        return cls.from_files(v01 / "dtteo_asset_model.ttl", mapping_files(v01), enabled)

    def lookup(self, source: str, device: str, field: str) -> PointMapping | None:
        """Return the mapping, or None if this field is unknown (-> quarantine)."""
        return self._table.get((source, device, field))

    def binding(self, source: str, device: str) -> Binding | None:
        """The installed device's binding (enabled or not), or None if it isn't bound."""
        return self._bindings.get((source, device))

    def __len__(self) -> int:
        return len(self._table)

    def rows(self):
        """All mappings, sorted. Used by the command-line check below."""
        return sorted(self._table.items())


class _Builder:
    """Start-up work: read the graph once, apply the rules, build the lookup table."""

    def __init__(self, graph: Graph, enabled_override: dict[str, bool]):
        self.g = graph
        self.enabled_override = enabled_override
        self.table: dict[tuple[str, str, str], PointMapping] = {}
        self.bindings: dict[tuple[str, str], Binding] = {}
        self.report: list[str] = []

        # point IRI -> (point_id, unit)
        self.points = {row.point: (str(row.point_id), _local_name(row.unit))
                       for row in graph.query(_POINTS)}
        self.value_maps: dict = {}
        for row in graph.query(_VALUE_MAPS):
            self.value_maps.setdefault(row.owner, {})[str(row["from"])] = str(row.to)

    def build(self) -> Mapper:
        self._add_field_refs()
        self._add_bindings()
        self._check_one_source_per_point()
        log.info("mapper loaded %d field mappings, %d bindings", len(self.table), len(self.bindings))
        return Mapper(self.table, self.bindings, self.report)

    # --- shared ---------------------------------------------------------------------
    def _mapping(self, point, raw_unit, scale, owner, where: str) -> PointMapping:
        if point not in self.points:
            # It could never be stored, so refuse now rather than per message.
            raise MappingError(f"{where}: point {_short(point)} has no ref:hasTimeseriesId")
        point_id, unit = self.points[point]
        return PointMapping(
            point_id=point_id,
            unit=unit,
            raw_unit=_local_name(raw_unit),
            scale=Decimal(str(scale)) if scale is not None else None,
            value_map=self.value_maps.get(owner),
        )

    def _put(self, key: tuple[str, str, str], mapping: PointMapping) -> None:
        if key in self.table and self.table[key] != mapping:
            raise MappingError(f"{key} is mapped to both {self.table[key].point_id} and {mapping.point_id}")
        self.table[key] = mapping

    # --- route 1: per-field references (irregular sources) ----------------------------
    def _add_field_refs(self) -> None:
        for row in self.g.query(_FIELD_REFS):
            key = (str(row.source), str(row.device), str(row.field))
            self._put(key, self._mapping(row.point, row.raw_unit, row.scale, row.raw, str(key)))

    # --- route 2: device types + bindings ----------------------------------------------
    def _add_bindings(self) -> None:
        decoders = {row.type: (str(row.decoder) if row.decoder else None) for row in self.g.query(_TYPES)}

        values: dict = {}       # type -> its value rows
        for row in self.g.query(_TYPE_VALUES):
            values.setdefault(row.type, []).append(row)

        places: dict = {}       # binding -> {field: point}
        for row in self.g.query(_PLACES):
            places.setdefault(row.b, {})[str(row.field)] = row.point

        rows: dict = {}         # binding -> rows (more than one means something was given twice)
        for row in self.g.query(_BINDINGS):
            rows.setdefault(row.b, []).append(row)

        for b, brows in sorted(rows.items()):
            name, row = _local_name(b), brows[0]

            # Rule 1: one device, one type that exists, serving something in the asset model.
            # "One type" follows WoT TD 1.1 section 9.4: a TD "can only be an instance of one TM at a time".
            if len({(r.device, r.type, r.serves) for r in brows}) > 1:
                raise MappingError(f"binding {name}: device, deviceType and serves must each be given once "
                                   "(a device is an instance of ONE type, as in WoT TD 1.1 section 9.4)")
            if row.device is None or row.type is None or row.serves is None:
                raise MappingError(f"binding {name}: needs dtteo:device, dtteo:deviceType and dtteo:serves")
            if row.type not in decoders:
                raise MappingError(f"binding {name}: device type {_short(row.type)} does not exist")
            if decoders[row.type] is None:
                raise MappingError(f"device type {_short(row.type)} has no dtteo:decoder")
            if (row.serves, RDF.type, None) not in self.g:
                raise MappingError(f"binding {name}: serves {_short(row.serves)}, which is not in the asset model")

            device, source = str(row.device), decoders[row.type]
            enabled = self.enabled_override.get(device, row.enabled is None or bool(row.enabled.toPython()))
            if (source, device) in self.bindings:
                raise MappingError(f"device {source}/{device} is bound twice")
            self.bindings[(source, device)] = Binding(
                source=source, device=device, device_type=_local_name(row.type),
                serves=_local_name(row.serves), enabled=enabled,
                timezone=str(row.tz) if row.tz else None, base=str(row.base) if row.base else None,
                registers=self._registers(name, values.get(row.type, [])))

            # Resolve every value, even for disabled bindings, so mistakes show up now.
            # Only enabled devices go into the lookup table.
            resolved = self._resolve(name, row.serves, values.get(row.type, []), dict(places.get(b, {})))
            if not enabled:
                self.report.append(f"{source}/{device}: binding disabled, its data will be quarantined")
                continue
            for field, mapping in resolved:
                self._put((source, device, field), mapping)

    def _resolve(self, name: str, serves, value_rows, placed: dict) -> list[tuple[str, PointMapping]]:
        out = []
        for v in value_rows:
            field = self._field_name(name, v)
            where = f"binding {name}, field {field!r}"
            if field in placed:
                point = placed.pop(field)              # the binding says exactly where it goes
            else:
                if v.cls is None:
                    raise MappingError(f"{where}: the type gives no dtteo:pointClass")
                found = [r.point for r in self.g.query(_CANDIDATES, initBindings={"serves": serves, "cls": v.cls})]
                if not found:
                    if v.optional is not None and v.optional.toPython():
                        self.report.append(f"{where}: optional, {_local_name(serves)} has no "
                                           f"{_short(v.cls)} point, so not mapped")
                        continue
                    # Rule 2: a required value must have a point to go to. Optional values
                    # follow WoT's tm:optional (TD 1.1 section 9.3.4).
                    raise MappingError(f"{where}: {_local_name(serves)} has no {_short(v.cls)} point in the "
                                       "asset model (add the point, or mark the value optional in the type)")
                if len(found) > 1:
                    pts = ", ".join(sorted(_short(p) for p in found))
                    raise MappingError(f"{where}: several {_short(v.cls)} points ({pts}); "
                                       "say which one with dtteo:place in the binding")
                point = found[0]
            out.append((field, self._mapping(point, v.raw_unit, v.scale, v.v, where)))
        if placed:
            raise MappingError(f"binding {name}: places field(s) {sorted(placed)} that its type does not have")
        return out

    def _registers(self, name: str, value_rows) -> dict:
        """Modbus values of a type -> {field: RegisterSpec}, checked against the data type."""
        from .decoders.modbus import FORMATS        # the decoder's list of supported types
        out = {}
        for v in value_rows:
            if v.entity is None:
                continue
            fld = self._field_name(name, v)
            if v.xsd is None or v.quantity is None:
                raise MappingError(f"binding {name}, field {fld!r}: Modbus values need modv:type and modv:quantity")
            xsd = _local_name(v.xsd)
            if xsd not in FORMATS:
                raise MappingError(f"binding {name}, field {fld!r}: xsd:{xsd} not supported by the Modbus decoder yet")
            if FORMATS[xsd][1] != int(v.quantity):
                raise MappingError(f"binding {name}, field {fld!r}: xsd:{xsd} takes {FORMATS[xsd][1]} "
                                   f"register(s), but modv:quantity is {int(v.quantity)}")
            out[fld] = RegisterSpec(
                entity=str(v.entity), address=int(v.address), quantity=int(v.quantity), xsd_type=xsd,
                msb_first=True if v.msb is None else bool(v.msb.toPython()),
                msw_first=True if v.msw is None else bool(v.msw.toPython()))
        return out

    @staticmethod
    def _field_name(name: str, v) -> str:
        if v.field is not None:
            return str(v.field)
        if v.entity is not None and v.address is not None:
            return f"{v.entity}:{int(v.address)}"             # Modbus, e.g. "InputRegister:12"
        raise MappingError(f"binding {name}: a type value has neither dtteo:field nor modv:entity + modv:address")

    # --- rule 3 -----------------------------------------------------------------------
    def _check_one_source_per_point(self) -> None:
        """
        One live source per point. Follows AWS SiteWise: "an asset property can only be
        linked to one data stream at a time".
        https://docs.aws.amazon.com/iot-sitewise/latest/userguide/data-streams.html
        """
        feeders: dict[str, list] = {}
        for key, m in self.table.items():
            feeders.setdefault(m.point_id, []).append(key)
        for point_id, keys in feeders.items():
            if len(keys) > 1:
                raise MappingError(f"{point_id} is fed by {len(keys)} sources {sorted(keys)}; "
                                   "only one may be enabled at a time")


# --- Command-line check: every mapping, plus anything worth knowing -------------------
#   python -m gateway.mapper        (v0.1's asset model + everything under mappings/)
# If the files are inconsistent it stops with a MappingError that says what to fix.
if __name__ == "__main__":
    v01 = Path(__file__).resolve().parents[3]
    m = Mapper.from_folder(v01)
    print(f"{'source':9} {'device':15} {'field':20} -> {'point':22} unit (raw)")
    for (source, device, field), pm in m.rows():
        raw = f" (raw {pm.raw_unit})" if pm.raw_unit else ""
        print(f"{source:9} {device:15} {field:20} -> {pm.point_id:22} {pm.unit or '-'}{raw}")
    if m.report:
        print("\nNotes:")
        for line in m.report:
            print(f"  - {line}")
    print(f"\nOK: {len(m)} field mappings.")
