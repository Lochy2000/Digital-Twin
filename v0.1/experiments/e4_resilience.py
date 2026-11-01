"""
E4: does the pipeline recover from failures by itself, without losing or duplicating readings?

A device sends 10 messages a second throughout (sensor times unique). Each scenario breaks one
part 20 s in, puts it back after the outage, then waits for the backlog to clear. "Put back" is
what Docker's restart policy (restart: unless-stopped) or the network coming back would do.

    sent      messages the device published
    stored    temperature readings in the database afterwards
    lost      sent - stored
    redelivered   copies the historian skipped thanks to the unique key (from its log)
    recovery_s    from "put back" until the last message sent during the outage was stored

    python experiments/e4_resilience.py            (all scenarios, about 20 minutes)
"""
from __future__ import annotations

import re
import socket
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import harness as h  # noqa: E402

RATE, WARM, AFTER = 10, 20, 40


class Proxy:
    """A TCP relay between the device and the broker that can 'lose the network'."""

    def __init__(self, listen: int = 1886, target: int = h.PORT):
        self.listen, self.target, self.up, self.conns = listen, target, True, []
        self.srv = socket.socket()
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("127.0.0.1", listen))
        self.srv.listen(16)
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while True:
            c, _ = self.srv.accept()
            if not self.up:
                c.close()
                continue
            s = socket.create_connection(("127.0.0.1", self.target))
            self.conns += [c, s]
            for a, b in ((c, s), (s, c)):
                threading.Thread(target=self._pipe, args=(a, b), daemon=True).start()

    def _pipe(self, a, b):
        try:
            while data := a.recv(65536):
                if not self.up:
                    break
                b.sendall(data)
        except OSError:
            pass
        for x in (a, b):
            try:
                x.close()
            except OSError:
                pass

    def cut(self):
        self.up = False
        for c in self.conns:
            try:
                c.shutdown(socket.SHUT_RDWR)
                c.close()
            except OSError:
                pass
        self.conns = []

    def restore(self):
        self.up = True


def scenario(name: str, outage: float, fault, restore, port: int = h.PORT, proxy: Proxy | None = None) -> dict:
    h.clear_tables()
    stack = h.Stack(f"e4_{name}").up()
    time.sleep(1)
    dev = h.Device(port=port, inflight=20)                 # paho default in-flight window, like the vendor publishers
    ts0 = h.now_ms() - 3_600_000
    total = WARM + outage + AFTER
    sender = threading.Thread(target=dev.run, args=(RATE, total, ts0))
    sender.start()
    time.sleep(WARM)
    t_fault = time.time()
    fault(stack)
    time.sleep(outage)
    t_restore = time.time()
    restore(stack)
    sender.join()
    dev.wait_published(timeout=180)
    n = len(dev.sent)
    rows = h.wait_stored(n, ts0, ts0 + n - 1, timeout=150, settle=10)
    stored = {ts: c for ts, c, _ in rows}
    sent = {s.ts: s.wall for s in dev.sent}
    lost = [ts for ts in sent if ts not in stored]
    during = [ts for ts, w in sent.items() if t_fault <= w <= t_restore and ts in stored]
    recovery = max(stored[ts] for ts in during) - t_restore if during else None
    lost_during = sum(1 for ts in lost if t_fault <= sent[ts] <= t_restore)
    alive = {k: p.poll() is None for k, p in stack.procs.items()}
    dup_rows = h.sql("SELECT count(*) - count(DISTINCT (series_id, sensor_time)) FROM readings")[0][0]
    text = (stack.logs / "historian.log").read_text()
    redeliv = sum(int(x) for x in re.findall(r"duplicates=(\d+)", text))
    dev.close()
    stack.down()
    if proxy:
        proxy.restore()
    r = {"scenario": name, "outage_s": outage, "sent": n, "stored": len(rows), "lost": len(lost),
         "lost_pct": round(100 * len(lost) / n, 2), "lost_sent_during_outage": lost_during,
         "duplicate_rows": dup_rows, "redelivered_skipped": redeliv,
         "recovery_s": round(recovery, 1) if recovery is not None else None,
         "all_services_up_after": all(alive.values())}
    print(r, flush=True)
    return r


def main():
    results = []
    proxy = Proxy()

    def run(name, outage, fault, restore, **kw):
        results.append(scenario(name, outage, fault, restore, **kw))
        h.write_csv("e4_resilience.csv", results)

    run("historian stopped (SIGTERM)", 60, lambda s: s.stop("historian"), lambda s: s.start("historian"))
    run("historian crashed (SIGKILL)", 60, lambda s: s.stop("historian", kill=True), lambda s: s.start("historian"))
    run("gateway crashed (SIGKILL)", 60, lambda s: s.stop("gateway", kill=True), lambda s: s.start("gateway"))
    run("database stopped", 60, lambda s: h.database("stop"), lambda s: h.database("start"))
    run("broker restarted cleanly (SIGTERM)", 15, lambda s: s.stop("broker"), lambda s: s.start("broker"))
    run("broker crashed (SIGKILL)", 15, lambda s: s.stop("broker", kill=True), lambda s: s.start("broker"))
    run("site network down (device to broker)", 60, lambda s: proxy.cut(), lambda s: proxy.restore(), port=1886, proxy=proxy)

    # Broker crash while the historian is away: its queued messages exist only in broker memory
    # until the next autosave (autosave_interval 60 in broker/mosquitto.conf).
    def fault(s):
        s.stop("historian")
        time.sleep(25)
        s.stop("broker", kill=True)

    def restore(s):
        s.start("broker")
        time.sleep(2)
        s.start("historian")
    run("broker crashed while historian away", 30, fault, restore)


if __name__ == "__main__":
    print(h.stamp(), "E4")
    main()
