"""
Show what the gateway does so far, using the captured sample messages.

    python -m gateway.demo

For each vendor message: decode it, look each field up in the mapper, and print
where every value would go. Grows as more gateway pieces are added.
"""
import json
from pathlib import Path

from .decoders import decode
from .mapper import Mapper

HERE = Path(__file__).resolve().parent
V01 = HERE.parents[2]
SAMPLES = HERE.parent / "tests" / "samples"


def main():
    mapper = Mapper.from_files(V01 / "dtteo_asset_model.ttl", sorted((V01 / "mappings").glob("*.ttl")))

    for sample in sorted(SAMPLES.glob("*.json")):
        s = json.loads(sample.read_text())
        print(f"\n{s['topic']}")
        print(f"  raw: {json.dumps(s['payload'])}")
        for r in decode(s["topic"], json.dumps(s["payload"]).encode()):
            m = mapper.lookup(r.source, r.device, r.field)
            where = m.point_id if m else "QUARANTINE (unknown point)"
            t = r.time.isoformat() if r.time else "-"
            print(f"  {r.field:12} = {str(r.value):8}  @ {t:32}  -> {where}")


if __name__ == "__main__":
    main()
