"""
Simulated sensor: each metric follows a heating or cooling curve towards an end value,
plus a little noise. For building and testing without hardware.

    [[sensors]]
    id = "tc08"
    type = "simulated"
    poll_s = 1
    unit = "DEG_C"                                  # default unit for its metrics
    [sensors.metrics]
    ch1 = { start = 30, end = 5, tau_s = 1800, noise = 0.05 }    # cools from 30 to 5, time constant 30 min
    humidity = { start = 55, noise = 0.3, unit = "PERCENT_RH" }  # no end: stays near start

value(t) = end + (start - end) * exp(-t / tau_s) + noise   (Newton's law of cooling, the same
shape as the matrix cool-down; t = seconds since the node started)
"""
from __future__ import annotations

import math
import random
import time

from dtnode.adapters.base import Adapter
from dtnode.reading import Reading


class SimulatedAdapter(Adapter):
    def connect(self) -> None:
        self.metrics = self.cfg.get("metrics") or {}
        if not self.metrics:
            raise ValueError(f"simulated sensor {self.id!r}: no [sensors.metrics]")
        self.t0 = time.monotonic()

    def read(self) -> list[Reading]:
        t, now, out = time.monotonic() - self.t0, self.now(), []
        for name, m in self.metrics.items():
            start = float(m.get("start", 20))
            end = float(m.get("end", start))
            tau = float(m.get("tau_s", 1))
            value = end + (start - end) * math.exp(-t / tau) + random.gauss(0, float(m.get("noise", 0)))
            out.append(Reading(self.point(name), round(value, 2), m.get("unit", self.cfg.get("unit")), now))
        return out
