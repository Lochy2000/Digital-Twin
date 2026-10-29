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
