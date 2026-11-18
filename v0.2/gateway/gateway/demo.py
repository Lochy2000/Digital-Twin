"""
Show what the gateway does so far, using the captured sample messages.

    python -m gateway.demo

For each message: decode -> map -> normalise -> validate, and print where every value ends up
and its quality (GOOD / SUSPECT / BAD).
Grows as more gateway pieces are added.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from dtteo_common.mapper import Mapper

from .decoders import decode, load_plugins
from .normaliser import NormaliseError, normalise
from .validator import with_quality

HERE = Path(__file__).resolve().parent
MODEL = HERE.parent / "model"
VENDORS = HERE.parent / "tests" / "vendors"        # fake Acme/Borealis, loaded as a plug-in
SAMPLES = [*sorted((HERE.parent / "tests" / "samples").glob("*.json")), *sorted((VENDORS / "samples").glob("*.json"))]


def main():
    # Acme, Borealis and the Tasmota probe all feed the zone temperature, so only one is
    # enabled at a time (bindings/site1.ttl). The demo swaps between them, as a real site would.
    load_plugins(VENDORS)
    def mapper_with(enabled=None):
        return Mapper.from_folder(MODEL, enabled, extra_dirs=[VENDORS / "mappings"])
    default = mapper_with()                             # Acme + SDM120 enabled
    mappers = {
        "acme": default,
        "sdm120": default,
        "borealis": mapper_with({"acme_hvac_0001": False, "site4_hvac_01": True}),
        "tasmota": mapper_with({"acme_hvac_0001": False, "tasmota_zone1": True}),
    }
    ingest = datetime.now(timezone.utc)

    for sample in SAMPLES:
        mapper = mappers[sample.stem]
        s = json.loads(sample.read_text())
        print(f"\n{s['topic']}")
        # The mapper doubles as the device registry: decoders ask it for the binding.
        for r in decode(s["topic"], json.dumps(s["payload"]).encode(), registry=mapper):
            raw = f"{r.field} = {r.value}"
            m = mapper.lookup(r.source, r.device, r.field)
            if m is None:
                b = mapper.binding(r.source, r.device)
                if b and b.enabled and mapper.why_unmapped(r.source, r.device, r.field):
                    print(f"  {raw:30} -> skipped: optional, no point in the asset model")
                else:
                    print(f"  {raw:30} -> QUARANTINE: unknown point")
                continue
            try:
                n = normalise(r, m, ingest, site="site1")
            except NormaliseError as e:
                print(f"  {raw:30} -> QUARANTINE: {e}")
                continue
            # The samples are recorded messages, so they're older than 6 h: switch the
            # stale-data check off here, or every one would be BAD.
            msg, verdict = with_quality(n, m, max_age=None)
            unit = f" {msg['unit']}" if msg["unit"] else ""
            why = f"  ({'; '.join(verdict.reasons)})" if verdict.reasons else ""
            print(f"  {raw:30} -> {msg['point']:20} = {msg['value']}{unit}  {msg['quality']}{why}")


if __name__ == "__main__":
    main()
