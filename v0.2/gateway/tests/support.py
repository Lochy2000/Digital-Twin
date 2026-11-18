"""
Where the tests find things, in one place (v0.2). Replaces the v0.1 tests' own
`V01 = Path(__file__).parents[3]`, which only worked inside the v0.1 folder.

    MODEL      gateway/model           the real asset model + mappings
    VENDORS    gateway/tests/vendors   fake Acme/Borealis: decoders, types, bindings, samples
    CONTRACTS  the installed dtteo_common.contracts (the JSON Schemas)

Importing this module registers the fake vendors' decoders (a plug-in, as in the dev setup).
"""
from pathlib import Path

from dtteo_common.contracts import HERE as CONTRACTS
from dtteo_common.mapper import Mapper, mapping_files

from gateway.decoders import load_plugins

TESTS = Path(__file__).resolve().parent
MODEL = TESTS.parent / "model"
VENDORS = TESTS / "vendors"
ASSET_MODEL = MODEL / "dtteo_asset_model.ttl"
SAMPLES = TESTS / "samples"                 # real formats (Tasmota, SDM120)
VENDOR_SAMPLES = VENDORS / "samples"        # fake vendors (Acme, Borealis)

load_plugins(VENDORS)


def model_mapper(enabled=None) -> Mapper:
    """The real model plus the fake vendors, as the v0.1 tests had it."""
    return Mapper.from_folder(MODEL, enabled, extra_dirs=[VENDORS / "mappings"])


def all_mapping_files() -> list[Path]:
    return mapping_files(MODEL, [VENDORS / "mappings"])


def sample_file(name: str) -> Path:
    """tests/samples/<name>.json, or the fake vendors' samples."""
    real = SAMPLES / f"{name}.json"
    return real if real.exists() else VENDOR_SAMPLES / f"{name}.json"
