"""v0.2 step D: a raw message is acknowledged only once its outputs are safe, and in arrival order."""
from gateway.acks import AckTracker


def make():
    acked = []
    return AckTracker(lambda mid, qos: acked.append(mid)), acked


def test_ack_waits_for_every_output():
    t, acked = make()
    t.received(1, 1, [101, 102])
    t.published(101)
    assert acked == []                 # one output still only in paho's memory
    t.published(102)
    assert acked == [1]


def test_acks_go_out_in_arrival_order():
    t, acked = make()
    t.received(1, 1, [101])
    t.received(2, 1, [102])
    t.published(102)                   # the newer message finishes first...
    assert acked == []                 # ...but MQTT says acks follow arrival order
    t.published(101)
    assert acked == [1, 2]


def test_message_with_no_outputs_is_acked_when_its_turn_comes():
    t, acked = make()
    t.received(1, 1, [])
    assert acked == [1]
    t.received(2, 1, [102])
    t.received(3, 1, [])
    assert acked == [1]
    t.published(102)
    assert acked == [1, 2, 3]


def test_reconnect_forgets_unacked_and_ignores_late_confirmations():
    t, acked = make()
    t.received(1, 1, [101])
    assert t.reconnected() == 1        # the broker will send message 1 again
    t.published(101)                   # paho re-sent the output on the new connection
    assert acked == [] and t.pending == 0


def test_unknown_confirmations_are_ignored():
    t, acked = make()
    t.published(999)                   # e.g. the gateway's own "online" status message
    t.received(1, 1, [101])
    t.published(101)
    assert acked == [1]


def test_qos0_raw_message_needs_no_ack_but_keeps_its_place():
    t, acked = make()
    t.received(1, 0, [101])
    t.received(2, 1, [])
    assert acked == []
    t.published(101)
    assert acked == [2]                # 1 was QoS 0: nothing to send for it


def test_oldest_wait_and_ack_count_for_the_health_check():
    now = [100.0]
    acked = []
    t = AckTracker(lambda mid, qos: acked.append(mid), clock=lambda: now[0])
    assert t.oldest_wait() == 0.0
    t.received(1, 1, [101])
    now[0] += 70
    assert t.oldest_wait() == 70                       # stuck: the health check reports this
    t.published(101)
    assert t.oldest_wait() == 0.0 and t.acked == 1
