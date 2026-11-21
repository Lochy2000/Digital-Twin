"""Batcher tests: retries while the database is down, acks in order, and never acks a
message from an older broker connection. No broker or database needed."""
import historian.service as service
from historian.service import Batcher, Received
from historian.store import Message, Result, StoreUnavailable


class FakeStore:
    def __init__(self, failures=0):
        self.failures, self.written = failures, []

    def write(self, messages):
        if self.failures:
            self.failures -= 1
            raise StoreUnavailable("database down")
        self.written.append(len(messages))
        return Result(readings=len(messages))


def received(mid, connection=1):
    return Received(Message("dt/v1/telemetry/site1/unit1/zone_air_temp", b"{}"), mid, 1, connection)


def make(store, connection=1):
    acks = []
    return Batcher(store, lambda mid, qos: acks.append(mid), lambda: connection, size=500, seconds=1), acks


def test_acks_only_after_the_write_and_in_order(monkeypatch):
    monkeypatch.setattr(service.time, "sleep", lambda s: None)
    store = FakeStore(failures=2)                     # database down for two tries
    b, acks = make(store)
    assert b.flush([received(3), received(4), received(5)], stop=lambda: False)
    assert store.written == [3] and acks == [3, 4, 5]


def test_message_from_an_older_connection_is_written_but_not_acked():
    b, acks = make(FakeStore(), connection=2)
    b.flush([received(7, connection=1), received(8, connection=2)], stop=lambda: False)
    assert acks == [8]                                # mid 7 belonged to the old connection


def test_stopping_while_the_database_is_down_acks_nothing(monkeypatch):
    monkeypatch.setattr(service.time, "sleep", lambda s: None)
    b, acks = make(FakeStore(failures=99))
    assert b.flush([received(1)], stop=lambda: True) is False
    assert acks == []                                 # the broker keeps it for next time


# --- v0.2 step D2: health ------------------------------------------------------------------

def test_healthy_when_writes_succeed():
    b, _ = make(FakeStore())
    b.flush([received(1), received(2)], stop=lambda: False)
    problems, counters = b.health()
    assert problems == [] and counters == {"stored": 2, "waiting": 0}


def test_database_down_is_unhealthy_until_a_write_succeeds(monkeypatch):
    monkeypatch.setattr(service.time, "sleep", lambda s: None)
    b, _ = make(FakeStore(failures=99))
    b.flush([received(1)], stop=lambda: True)          # gave up while the database was down
    assert b.health()[0][0].startswith("database unavailable")
    b.store = FakeStore()
    b.flush([received(1)], stop=lambda: False)
    assert b.health()[0] == []


def test_waiting_messages_with_nothing_stored_for_a_minute_is_stuck():
    b, _ = make(FakeStore())
    b.inbox.put(received(1))
    assert b.health()[0] == []                         # just arrived: fine
    b.last_stored -= service.STUCK_AFTER + 1
    assert "nothing stored" in b.health()[0][0]
