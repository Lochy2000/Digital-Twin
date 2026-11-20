"""
The outbox: every message waits here, in a small SQLite file, until the broker confirms it.

    sensor read ──► outbox.put() ──► (sender) publish ──► broker says "got it" ──► outbox.remove()

Why a file and not memory: a node can lose power or Wi-Fi at any moment. Messages in the
file survive both and are sent when the broker is reachable again, oldest first
("transactional outbox" / store-and-forward). A message removed only after the broker's
acknowledgement can, in the worst case, be sent twice; the platform ignores duplicates.

Size limit: max_messages. When full, the OLDEST messages are dropped (and counted), so a
long outage can't fill the SD card, and what is kept is the most recent data.

SD-card wear: SQLite's WAL mode with synchronous=NORMAL writes small appends rather than
rewriting the file; one row per sensor poll, not per reading.

Sources: SQLite WAL https://www.sqlite.org/wal.html ; synchronous https://www.sqlite.org/pragma.html#pragma_synchronous
"""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path


class Outbox:
    def __init__(self, path: Path | str, max_messages: int = 100_000):
        self.max_messages = max_messages
        self.dropped = 0                                 # oldest messages dropped because the outbox was full
        self._lock = threading.Lock()                    # sensor threads put, the sender removes
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._db.execute("""CREATE TABLE IF NOT EXISTS outbox (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                topic TEXT NOT NULL,
                                payload BLOB NOT NULL,
                                created REAL NOT NULL)""")

    def put(self, topic: str, payload: bytes) -> None:
        with self._lock:
            self._db.execute("INSERT INTO outbox (topic, payload, created) VALUES (?, ?, ?)",
                             (topic, payload, time.time()))
            over = self._count() - self.max_messages
            if over > 0:
                self._db.execute("DELETE FROM outbox WHERE id IN (SELECT id FROM outbox ORDER BY id LIMIT ?)", (over,))
                self.dropped += over

    def oldest(self, limit: int, skip: set[int] = frozenset()) -> list[tuple[int, str, bytes]]:
        """Up to `limit` waiting messages, oldest first, leaving out ids already being sent."""
        with self._lock:
            rows = self._db.execute("SELECT id, topic, payload FROM outbox ORDER BY id LIMIT ?",
                                    (limit + len(skip),)).fetchall()
        return [r for r in rows if r[0] not in skip][:limit]

    def remove(self, message_id: int) -> None:
        with self._lock:
            self._db.execute("DELETE FROM outbox WHERE id = ?", (message_id,))

    def count(self) -> int:
        with self._lock:
            return self._count()

    def _count(self) -> int:
        return self._db.execute("SELECT count(*) FROM outbox").fetchone()[0]

    def close(self) -> None:
        with self._lock:
            self._db.close()
