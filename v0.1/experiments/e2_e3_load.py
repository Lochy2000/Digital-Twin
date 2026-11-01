"""
E2 (latency) and E3 (throughput): one device sends Acme messages at a fixed rate; every message
becomes 2 readings (temperature + mode; humidity is counted and dropped, step 2l).

Times measured per temperature reading, all on one clock:
    sent      when the device called publish()
    gateway   ingest_time inside the canonical message (gateway received it)
    out       when a watcher (engineer login) received the canonical message      (E2 only)
    stored    PostgreSQL commit time of the row (track_commit_timestamp = on)

Sustained capacity (E3), defined before running: the highest offered rate at which stored
throughput is >= 95% of the offered rate AND the backlog clears within 5 s of the last send.

    python experiments/e2_e3_load.py e2      latency, 5 rates x 3 repeats
    python experiments/e2_e3_load.py e2b     the same with BATCH_SECONDS=0.2 (a setting, not code)
    python experiments/e2_e3_load.py e2c     Mosquitto set_tcp_nodelay off vs on, at 100/s
    python experiments/e2_e3_load.py e3      throughput, 8 rates x 2 repeats
"""
from __future__ import annotations

import json
import statistics as st
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import harness as h  # noqa: E402
import paho.mqtt.client as mqtt  # noqa: E402

E2_RATES = [(1, 60), (10, 30), (50, 20), (100, 20), (250, 20)]        # (messages/s, seconds)
E3_RATES = [(250, 20), (500, 20), (750, 20), (1000, 20), (1500, 20), (2000, 20), (3000, 20), (4000, 20)]
NEXT_TS = [None]          # sensor times handed out so far: every run gets its own range (no overlaps)
REPEATS = 3


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))]


class Watcher:
    """Receives canonical temperature messages as the read-only engineer login."""

    def __init__(self):
        self.got: dict[int, tuple[float, float]] = {}           # sensor ms -> (ingest epoch, received epoch)
        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="exp_watcher")
        c.username_pw_set("engineer", h.PASSWORDS["engineer"])
        ready = threading.Event()
        c.on_connect = lambda c_, u, f, rc, p: (c_.subscribe("dt/v1/telemetry/site1/unit1/zone_air_temp", 1), ready.set())
        c.on_message = self._on
        c.connect("127.0.0.1", h.PORT)
        c.loop_start()
        ready.wait(5)
        time.sleep(0.5)
        self.c = c

    def _on(self, c, u, m):
        now = time.time()
        b = json.loads(m.payload)
        s = int(datetime.fromisoformat(b["sensor_time"].replace("Z", "+00:00")).timestamp() * 1000)
        self.got[s] = (datetime.fromisoformat(b["ingest_time"].replace("Z", "+00:00")).timestamp(), now)

    def close(self):
        self.c.loop_stop()
        self.c.disconnect()


def one_run(rate: float, seconds: float, watch: bool, stack: h.Stack, run_id: str) -> tuple[dict, list[dict]]:
    dev = h.Device()
    watcher = Watcher() if watch else None
    pids = {"broker": stack.pid("broker"), "gateway": stack.pid("gateway"), "historian": stack.pid("historian")}
    sampler = h.Sampler(pids)
    if NEXT_TS[0] is None:
        NEXT_TS[0] = h.now_ms() - 5 * 3_600_000                    # 5 h ago: inside the 6 h late_arrival limit
    ts0 = NEXT_TS[0]
    NEXT_TS[0] += int(rate * seconds) + 10_000
    drops0 = (stack.logs / "gateway.log").read_text().count("publish_dropped")
    dev.run(rate, seconds, ts0)
    t_sent = time.time()
    dev.wait_published()
    n = len(dev.sent)
    rows = h.wait_stored(n, ts0, ts0 + n - 1, timeout=max(30, seconds * 3))
    cpu = sampler.stop()
    if watcher:
        time.sleep(0.5)
        watcher.close()
    dev.close()

    drops = (stack.logs / "gateway.log").read_text().count("publish_dropped") - drops0
    acked = sorted(dev.acked)
    sent = {s.ts: s.wall for s in dev.sent}
    per = []
    for ts, commit, q in rows:
        r = {"run": run_id, "rate": rate, "ts": ts, "sent": sent[ts], "stored_s": commit - sent[ts]}
        if watcher and ts in watcher.got:
            ingest, recv = watcher.got[ts]
            r.update(gateway_in_s=ingest - sent[ts], gateway_out_s=recv - sent[ts])
        per.append(r)
    lat = [r["stored_s"] for r in per]
    commits = [c for _, c, _ in rows]
    offered = n / (dev.sent[-1].wall - dev.sent[0].wall) if n > 1 else rate
    summary = {
        "run": run_id, "target_rate": rate, "seconds": seconds, "sent": n, "stored": len(rows), "lost": n - len(rows),
        "offered_msg_s": round(offered, 1),
        "broker_accepted_msg_s": round(len(acked) / (acked[-1] - acked[0]), 1) if len(acked) > 1 else None,
        "gateway_dropped_readings": drops,
        "stored_msg_s": round(len(rows) / (max(commits) - min(commits)), 1) if len(rows) > 1 else None,
        "drain_s": round(max(commits) - t_sent, 2) if rows else None,
        "p50_ms": round(1000 * st.median(lat)), "p95_ms": round(1000 * pct(lat, 95)),
        "p99_ms": round(1000 * pct(lat, 99)), "max_ms": round(1000 * max(lat)),
    }
    if watcher:
        g = [r["gateway_out_s"] for r in per if "gateway_out_s" in r]
        summary.update(gw_out_p50_ms=round(1000 * st.median(g), 1), gw_out_p99_ms=round(1000 * pct(g, 99), 1))
    for k in pids:
        vals = [row.get(f"{k}_cpu") for row in cpu if row.get(f"{k}_cpu") is not None]
        mem = [row.get(f"{k}_mb") for row in cpu if row.get(f"{k}_mb") is not None]
        summary[f"{k}_cpu_mean"] = round(st.mean(vals), 1) if vals else None
        summary[f"{k}_mb_max"] = round(max(mem), 1) if mem else None
    return summary, per


def batch_variant():
    """E2b, a setting not the code: the historian's batch window (BATCH_SECONDS) at 0.2 s instead of 1 s."""
    summaries = []
    h.clear_tables()
    stack = h.Stack("e2b", historian_env={"BATCH_SECONDS": "0.2"}).up()
    time.sleep(2)
    for rate, seconds in [(10, 30), (100, 20), (250, 20)]:
        s, _ = one_run(rate, seconds, True, stack, f"e2b-{rate}")
        s["batch_seconds"] = 0.2
        summaries.append(s)
        print({k: s[k] for k in ("run", "p50_ms", "p95_ms", "p99_ms", "max_ms", "historian_cpu_mean")}, flush=True)
    stack.down()
    h.write_csv("e2b_batch_window.csv", summaries)


def nodelay_variant():
    """E2c, a setting not the code: Mosquitto's set_tcp_nodelay true (default false), to test whether the
    ~45 ms gateway-out step at >= 50 msg/s is Nagle's algorithm meeting delayed ACKs."""
    summaries = []
    for label, extra in (("default", ""), ("set_tcp_nodelay true", "set_tcp_nodelay true")):
        h.clear_tables()
        stack = h.Stack(f"e2c_{label.replace(' ', '_')}", broker_extra=extra).up()
        time.sleep(2)
        s, _ = one_run(100, 20, True, stack, f"e2c-{label}")
        s["broker_setting"] = label
        summaries.append(s)
        print({k: s[k] for k in ("run", "gw_out_p50_ms", "gw_out_p99_ms", "p99_ms")}, flush=True)
        stack.down()
    h.write_csv("e2c_tcp_nodelay.csv", summaries)


def main(which: str):
    if which == "e2b":
        return batch_variant()
    if which == "e2c":
        return nodelay_variant()
    rates, watch = (E2_RATES, True) if which == "e2" else (E3_RATES, False)
    summaries, per_all = [], []
    for rep in range(1, REPEATS + 1 if which == "e2" else 3):
        h.clear_tables()
        stack = h.Stack(f"{which}_rep{rep}").up()
        time.sleep(2)
        for rate, seconds in rates:
            s, per = one_run(rate, seconds, watch, stack, f"{which}-r{rep}-{rate}")
            s["repeat"] = rep
            summaries.append(s)
            per_all += per
            print({k: s[k] for k in ("run", "offered_msg_s", "stored_msg_s", "lost", "drain_s", "p50_ms", "p95_ms", "p99_ms", "max_ms")}, flush=True)
            time.sleep(2)
        stack.down()
    h.write_csv(f"{which}_summary.csv", summaries)
    h.write_csv(f"{which}_per_reading.csv", per_all)


if __name__ == "__main__":
    print(h.stamp(), sys.argv[1])
    main(sys.argv[1])
