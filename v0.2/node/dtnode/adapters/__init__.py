"""
Which adapter handles which sensor `type` in node.toml.

Adapters are imported only when a node's config uses them, so a node never needs the libraries
of sensors it doesn't have (the Lepton's OpenCV only on the camera node, etc.).
Real-hardware adapters (lepton, mlx90640, tc08, bme280, tapo_p110) come over from dt-edge later.
"""
from __future__ import annotations

import importlib

TYPES = {
    "simulated": "dtnode.adapters.simulated:SimulatedAdapter",
    "csv": "dtnode.adapters.csv_replay:CsvReplayAdapter",
}


def make(cfg: dict):
    target = TYPES.get(cfg["type"])
    if target is None:
        raise ValueError(f"sensor {cfg['id']!r}: unknown type {cfg['type']!r} (known: {', '.join(sorted(TYPES))})")
    module, cls = target.split(":")
    return getattr(importlib.import_module(module), cls)(cfg)
