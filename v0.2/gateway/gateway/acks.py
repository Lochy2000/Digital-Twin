"""
Acknowledge a raw message only after everything made from it is safely with the broker.

Why (v0.2 step D): paho normally acknowledges a message as soon as on_message returns. The
gateway's outputs are still in paho's memory at that point, waiting their turn to be sent, so a
crash then loses them: the broker thinks the raw message was handled and won't send it again.
Measured before this change: killing the gateway while it drained a backlog lost up to 40% of
the readings (dev kill test, 20 Nov 2026).

How:
  1. manual acks (paho manual_ack_set(True)): the gateway sends each PUBACK itself.
  2. For every raw message, remember the message ids of its outputs. When the broker has
     confirmed all of them (on_publish), the raw message is done.
  3. Acks go out in the order the raw messages arrived, as MQTT requires ("It MUST send PUBACK
     packets in the order in which the corresponding PUBLISH packets were received", MQTT 5.0
     section 4.6). A finished message waits for any older one that isn't finished yet.
  4. After a reconnect, anything not yet acked is forgotten: the broker re-sends it (persistent
     session), the gateway processes it again, and the copies are skipped downstream (the
     historian's unique key on series + sensor_time). Acks are only valid on the connection
     the message arrived on.

Same pattern as the historian (platform/historian/historian/service.py), where "safe" means the
database has committed instead of the broker has confirmed.

Threads: paho runs on_message and on_publish on its one network thread, so the broker's
confirmation of an output can't be handled before on_message has finished registering it.

Sources:
  - paho-mqtt 2.1.0 Client.manual_ack_set / Client.ack / on_publish
  - MQTT 5.0 section 4.6 Message ordering:
      https://docs.oasis-open.org/mqtt/mqtt/v5.0/os/mqtt-v5.0-os.html
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Iterable


@dataclass
class _Entry:
    mid: int                                   # the raw message's id (what we acknowledge)
    qos: int
    waiting: set[int] = field(default_factory=set)   # output ids the broker hasn't confirmed yet


class AckTracker:
    """Holds each raw message's ack until all its outputs are confirmed, then acks in order."""

    def __init__(self, ack: Callable[[int, int], object]):
        self._ack = ack
        self._line: deque[_Entry] = deque()     # raw messages in arrival order
        self._by_output: dict[int, _Entry] = {}  # output id -> the raw message it came from

    def received(self, mid: int, qos: int, output_mids: Iterable[int]) -> None:
        """A raw message was processed and its outputs handed to paho (their ids)."""
        entry = _Entry(mid, qos, set(output_mids))
        for out in entry.waiting:
            self._by_output[out] = entry
        self._line.append(entry)
        self._release()

    def published(self, output_mid: int) -> None:
        """The broker confirmed one output. Unknown ids (status messages, old connection) are ignored."""
        entry = self._by_output.pop(output_mid, None)
        if entry is not None:
            entry.waiting.discard(output_mid)
            self._release()

    def reconnected(self) -> int:
        """Forget everything not yet acked; the broker will send it again. Returns how many."""
        dropped = len(self._line)
        self._line.clear()
        self._by_output.clear()
        return dropped

    @property
    def pending(self) -> int:
        """Raw messages received but not yet acknowledged."""
        return len(self._line)

    def _release(self) -> None:
        while self._line and not self._line[0].waiting:
            entry = self._line.popleft()
            if entry.qos > 0:                   # QoS 0 has nothing to acknowledge
                self._ack(entry.mid, entry.qos)
