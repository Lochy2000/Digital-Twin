"""
The contract every sensor adapter follows. One adapter per sensor TYPE; a device's node.toml
says which sensors it has. To add a sensor type: one new file here + one line in adapters/__init__.py.

    class MySensor(Adapter):
        def connect(self): ...          # open the device; raise if it isn't there
        def read(self): ...             # return a list of Reading (may be empty)
        def close(self): ...            # release the device (optional)
"""
from __future__ import annotations

from datetime import datetime, timezone

from dtnode.reading import Reading


class Adapter:
    def __init__(self, cfg: dict):
        self.cfg = cfg                  # this sensor's [[sensors]] block from node.toml
        self.id = cfg["id"]

    def point(self, metric: str) -> str:
        return f"{self.id}.{metric}"

    @property
    def source(self) -> str:
        return f"{self.cfg['type']}:{self.id}"

    @staticmethod
    def now() -> datetime:
        return datetime.now(timezone.utc)

    def connect(self) -> None:
        """Open the device. Raise an exception if it can't be reached."""

    def read(self) -> list[Reading]:
        raise NotImplementedError

    def close(self) -> None:
        """Release the device."""
