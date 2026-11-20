from dtnode.outbox import Outbox


def test_messages_come_out_oldest_first_and_stay_until_removed(tmp_path):
    box = Outbox(tmp_path / "outbox.db")
    for i in range(3):
        box.put("t", f"m{i}".encode())
    rows = box.oldest(10)
    assert [r[2] for r in rows] == [b"m0", b"m1", b"m2"]
    box.remove(rows[0][0])
    assert box.count() == 2 and box.oldest(10)[0][2] == b"m1"


def test_messages_survive_a_restart(tmp_path):
    Outbox(tmp_path / "outbox.db").put("t", b"kept")
    assert Outbox(tmp_path / "outbox.db").oldest(1)[0][2] == b"kept"      # a new process, same file


def test_when_full_the_oldest_are_dropped_and_counted(tmp_path):
    box = Outbox(tmp_path / "outbox.db", max_messages=3)
    for i in range(5):
        box.put("t", str(i).encode())
    assert [r[2] for r in box.oldest(10)] == [b"2", b"3", b"4"] and box.dropped == 2


def test_messages_already_being_sent_are_skipped(tmp_path):
    box = Outbox(tmp_path / "outbox.db")
    for i in range(3):
        box.put("t", str(i).encode())
    first = box.oldest(1)[0][0]
    assert [r[2] for r in box.oldest(10, skip={first})] == [b"1", b"2"]
