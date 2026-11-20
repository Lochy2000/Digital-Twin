"""
One reading, and the message it becomes: the same shape dt-edge sends (dt-edge app/record.py),
which the gateway's `dtedge` decoder already reads. Kept identical so a dt-node and the current
rig look the same to the gateway.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

VERSION = 2


@dataclass
class Reading:
    point_id: str                         # "<sensor id>.<metric>", e.g. "tc08.ch1"
    value: float | int | str | bool | None
    unit: str | None                      # QUDT id, e.g. DEG_C, PERCENT_RH, HectoPA
    time: datetime                        # when it was measured (timezone-aware, from this device's clock)
    quality: str = "GOOD"                 # the sensor's own verdict: GOOD / SUSPECT / BAD
    qc: list[str] = field(default_factory=list)

    def to_message(self, source: str) -> dict:
        return {"v": VERSION, "point_id": self.point_id, "value": self.value, "unit": self.unit,
                "sensor_time": self.time.isoformat(), "quality": self.quality, "qc": self.qc or None,
                "time_source": "device", "source": source}
