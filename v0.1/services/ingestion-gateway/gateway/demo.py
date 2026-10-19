"""
Show what the gateway does so far, using the captured sample messages.

    python -m gateway.demo

For each vendor message: decode -> map -> normalise, and print where every value ends up.
Grows as more gateway pieces are added.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from .decoders import decode
from .mapper import Mapper
from .normaliser import NormaliseError, normalise

HERE = Path(__file__).resolve().parent
V01 = HERE.parents[2]
SAMPLES = HERE.parent / "tests" / "samples"


def main():
    # Acme, Borealis and the Tasmota probe all feed the zone temperature, so only one is
    # enabled at a time (bindings/site1.ttl). The demo swaps between them, as a real site would.
    default = Mapper.from_folder(V01)                   # Acme + SDM120 enabled
    mappers = {
        "acme": default,
        "sdm120": default,
        "borealis": Mapper.from_folder(V01, enabled={"acme_hvac_0001": False, "site4_hvac_01": True}),
        "tasmota": Mapper.from_folder(V01, enabled={"acme_hvac_0001": False, "tasmota_zone1": True}),
    }
    ingest = datetime.now(timezone.utc)

    for sample in sorted(SAMPLES.glob("*.json")):
        mapper = mappers[sample.stem]
        s = json.loads(sample.read_text())
        print(f"\n{s['topic']}")
        # The mapper doubles as the device registry: decoders ask it for the binding.
        for r in decode(s["topic"], json.dumps(s["payload"]).encode(), registry=mapper):
            raw = f"{r.field} = {r.value}"
            m = mapper.lookup(r.source, r.device, r.field)
            if m is None:
                print(f"  {raw:30} -> QUARANTINE: unknown point")
                continue
            try:
                n = normalise(r, m, ingest)
            except NormaliseError as e:
                print(f"  {raw:30} -> QUARANTINE: {e}")
                continue
            unit = f" {n['unit']}" if n["unit"] else ""
            print(f"  {raw:30} -> {n['point']:20} = {n['value']}{unit}  @ {n['sensor_time']}")


if __name__ == "__main__":
    main()
