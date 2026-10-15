"""
Mapper: "which point is this?"

Answers one question for the rest of the gateway:

    (source, device, field)  ->  point ID + unit info      e.g.
    ("acme", "acme_hvac_0001", "tempF")  ->  unit1.zone_air_temp, DEG_C (raw DEG_F)

It reads two kinds of Turtle file:
  - the asset model (dtteo_asset_model.ttl): what each point IS, its unit, its point ID
  - mapping files   (mappings/*.ttl):        where each point appears in a vendor's raw message

Both are loaded into ONE graph and joined with a single SPARQL query. After loading,
lookups are a plain dictionary read, so the graph is never queried per message.

If a lookup returns None, the point is unknown and the reading goes to quarantine.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Iterable

from rdflib import Graph

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PointMapping:
    point_id: str             # canonical ID, e.g. "unit1.zone_air_temp"
    unit: str | None          # point's unit (QUDT local name), e.g. "DEG_C"; None if unitless
    raw_unit: str | None      # unit the vendor sends in, if different, e.g. "DEG_F"
    scale: Decimal | None     # multiply raw number by this first, e.g. 0.01


class MappingError(Exception):
    """The model or mapping files are inconsistent. Raised at start-up, never per message."""


# One query joins the asset model and the mapping files:
#   point --hasExternalReference--> RawFieldReference (source, device, field, ...)
#   point --hasExternalReference--> TimeseriesReference (point ID)
#   point --hasUnit--> unit (optional)
_QUERY = """
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX ref:   <https://brickschema.org/schema/Brick/ref#>
PREFIX dtteo: <urn:dtteo:schema#>
SELECT ?source ?device ?field ?point_id ?unit ?raw_unit ?scale WHERE {
    ?point ref:hasExternalReference ?raw .
    ?raw a dtteo:RawFieldReference ;
         dtteo:source ?source ;
         dtteo:device ?device ;
         dtteo:field  ?field .
    OPTIONAL { ?raw dtteo:rawUnit ?raw_unit }
    OPTIONAL { ?raw dtteo:scale   ?scale }
    OPTIONAL {
        ?point ref:hasExternalReference ?ts .
        ?ts a ref:TimeseriesReference ;
            ref:hasTimeseriesId ?point_id .
    }
    OPTIONAL { ?point brick:hasUnit ?unit }
}
"""


def _local_name(uri) -> str | None:
    """http://qudt.org/vocab/unit/DEG_C  ->  DEG_C"""
    if uri is None:
        return None
    return str(uri).rstrip("/").rsplit("/", 1)[-1].rsplit("#", 1)[-1]


class Mapper:
    def __init__(self, table: dict[tuple[str, str, str], PointMapping]):
        self._table = table

    @classmethod
    def from_files(cls, asset_model: Path, mapping_files: Iterable[Path]) -> "Mapper":
        graph = Graph()
        graph.parse(asset_model, format="turtle")
        for path in mapping_files:
            graph.parse(path, format="turtle")

        table: dict[tuple[str, str, str], PointMapping] = {}
        for row in graph.query(_QUERY):
            key = (str(row.source), str(row.device), str(row.field))

            if row.point_id is None:
                # A vendor field points at something with no point ID -> it could never be stored.
                raise MappingError(f"{key} maps to a point with no ref:hasTimeseriesId")

            mapping = PointMapping(
                point_id=str(row.point_id),
                unit=_local_name(row.unit),
                raw_unit=_local_name(row.raw_unit),
                scale=Decimal(str(row.scale)) if row.scale is not None else None,
            )
            if key in table and table[key] != mapping:
                # Same vendor field claimed by two different points -> ambiguous.
                raise MappingError(f"{key} is mapped to both {table[key].point_id} and {mapping.point_id}")
            table[key] = mapping

        log.info("mapper loaded %d raw field mappings", len(table))
        return cls(table)

    def lookup(self, source: str, device: str, field: str) -> PointMapping | None:
        """Return the mapping, or None if this field is unknown (-> quarantine)."""
        return self._table.get((source, device, field))

    def __len__(self) -> int:
        return len(self._table)

    def rows(self):
        """All mappings, sorted. Used by the command-line listing below."""
        return sorted(self._table.items())


# --- Command-line helper: print every mapping the gateway knows about ---------------
#   python -m gateway.mapper                      (uses v0.1's asset model + mappings/ folder)
#   python -m gateway.mapper MODEL.ttl MAPDIR     (or point it at other files)
# Folders are searched for *.ttl here in Python, so it works the same on Windows.
if __name__ == "__main__":
    import sys

    v01 = Path(__file__).resolve().parents[3]
    model = Path(sys.argv[1]) if len(sys.argv) > 1 else v01 / "dtteo_asset_model.ttl"
    map_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else v01 / "mappings"
    m = Mapper.from_files(model, sorted(map_dir.glob("*.ttl")))
    print(f"{'source':10} {'device':16} {'field':14} -> {'point':22} unit (raw)")
    for (source, device, field), pm in m.rows():
        raw = f" (raw {pm.raw_unit})" if pm.raw_unit else ""
        print(f"{source:10} {device:16} {field:14} -> {pm.point_id:22} {pm.unit or '-'}{raw}")
