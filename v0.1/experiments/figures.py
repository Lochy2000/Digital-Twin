"""
Charts for FINDINGS.md, drawn from the CSVs in results/ (nothing typed in by hand).

    python experiments/figures.py            -> experiments/figures/*.png

Style as the other v0.1 diagrams: black, greys and one teal (#0E6E68) for what matters,
IBM Plex Sans, series named on the chart instead of in a legend.
"""
from __future__ import annotations

import csv
import os
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402

HERE = Path(__file__).resolve().parent
RES, FIG = HERE / "results", HERE / "figures"
FIG.mkdir(exist_ok=True)
TEAL, INK, GREY, LIGHT, FAINT = "#0E6E68", "#1A1A1A", "#6B6B6B", "#BDBDBD", "#E6E6E6"

for d in [os.getenv("PLEX_TTF_DIR", ""), "/usr/share/fonts/truetype/ibm-plex"]:
    if d and Path(d).is_dir():
        for f in Path(d).glob("*.ttf"):
            font_manager.fontManager.addfont(str(f))
plt.rcParams.update({
    "font.family": ["IBM Plex Sans", "DejaVu Sans"], "font.size": 10, "axes.edgecolor": GREY, "axes.labelcolor": INK,
    "xtick.color": GREY, "ytick.color": GREY, "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": FAINT, "grid.linewidth": 0.8, "axes.axisbelow": True,
    "axes.titlesize": 12, "axes.titleweight": "semibold", "axes.titlelocation": "left", "figure.dpi": 100,
    "savefig.dpi": 200, "savefig.bbox": "tight", "savefig.facecolor": "white",
})


def rows(name):
    with open(RES / name) as f:
        return list(csv.DictReader(f))


def note(fig, text):
    fig.text(0.0, -0.02, text, ha="left", va="top", fontsize=8, color=GREY, wrap=True)


# --- E1 ------------------------------------------------------------------------------------------
def e1():
    s = [r for r in rows("e1_sensor_faults_samples.csv") if r["device"] == "acme"]
    from datetime import datetime
    t = [datetime.fromisoformat(r["sensor_time"]) for r in s]
    v = [float(r["value_c"]) for r in s]
    fig, (ax, bx) = plt.subplots(2, 1, figsize=(10, 6.6), gridspec_kw={"height_ratios": [1.5, 1]})
    ax.plot(t, v, color=LIGHT, lw=0.8, zorder=1)
    faulty_missed = [(ti, vi) for ti, vi, r in zip(t, v, s) if r["label"] != "clean" and r["quality"] == "GOOD"]
    flagged = [(ti, vi) for ti, vi, r in zip(t, v, s) if r["quality"] != "GOOD"]
    if faulty_missed:
        ax.scatter(*zip(*faulty_missed), s=6, color=INK, zorder=2, lw=0)
    if flagged:
        ax.scatter(*zip(*flagged), s=22, color=TEAL, zorder=3, lw=0)
    ax.axhspan(5, 35, color=TEAL, alpha=0.05, lw=0)
    ax.text(t[20], 34.2, "expected range 5–35 °C (the only check that can fire here)", color=TEAL, fontsize=8.5, va="top")
    ax.set_ylabel("zone air temperature, °C")
    ax.set_title("E1  Three days of zone temperature with faults injected: what the gateway flags")
    marks = [("spikes +6 °C", 700, 30), ("spikes +20 °C", 2100, 44), ("step +7 °C", 2930, 31.5), ("stuck 2 h", 3060, 17),
             ("drift +3 °C/day", 3950, 27.5), ("drop to 0 °C", 1300, 2.5)]
    for label, i, y in marks:
        ax.text(t[i], y, label, fontsize=8.5, color=INK, ha="center")
    ax.text(t[-1], 41, "teal = flagged SUSPECT/BAD\nblack = faulty but passed as GOOD", ha="right", fontsize=8.5, color=GREY, va="top")
    ax.set_ylim(-2, 46)

    summ = [r for r in rows("e1_sensor_faults.csv") if not r["fault"].startswith("clean")]
    order = sorted(summ, key=lambda r: float(r["flagged_pct"]))
    names = [r["fault"] for r in order]
    pcts = [float(r["flagged_pct"]) for r in order]
    y = range(len(order))
    bx.barh(y, [100] * len(order), color=FAINT, height=0.6)
    bx.barh(y, pcts, color=[TEAL if p > 0 else INK for p in pcts], height=0.6)
    for yi, r in zip(y, order):
        p = float(r["flagged_pct"])
        txt = f"{p:.0f}%  ({r['flagged']}/{r['samples']})" + (f"  by {r['by_test']}" if p else "  no check exists (needs history: QARTOD spike / rate / flat line)")
        bx.text(101 if p >= 100 else max(p, 0) + 1, yi, txt, va="center", fontsize=8.5, color=INK)
    bx.set_yticks(list(y), names, fontsize=8.5)
    bx.set_xlim(0, 175)
    bx.set_xticks([0, 25, 50, 75, 100])
    bx.set_xlabel("faulty samples flagged, %")
    bx.grid(axis="y", visible=False)
    clean = [r for r in rows("e1_sensor_faults.csv") if r["fault"].startswith("clean")]
    note(fig, "False alarms on clean data: " + ", ".join(f"{r['flagged']} of {r['samples']} ({r['fault']})" for r in clean)
         + ".  Source: results/e1_sensor_faults*.csv")
    fig.tight_layout()
    fig.savefig(FIG / "e1_fault_detection.png")


# --- E2 ------------------------------------------------------------------------------------------
def e2():
    per = rows("e2_per_reading.csv")
    by = defaultdict(list)
    gw = defaultdict(list)
    for r in per:
        by[float(r["rate"])].append(1000 * float(r["stored_s"]))
        if r.get("gateway_out_s"):
            gw[float(r["rate"])].append(1000 * float(r["gateway_out_s"]))
    rates = sorted(by)
    fig, ax = plt.subplots(figsize=(9, 4.2))
    def pc(xs, p):
        xs = sorted(xs)
        return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))]
    import random
    random.seed(1)
    x = range(len(rates))
    for i, r in zip(x, rates):
        d = by[r]
        sample = random.sample(d, min(600, len(d)))
        ax.scatter([i + random.uniform(-0.18, 0.18) for _ in sample], sample, s=3, color=LIGHT, lw=0, zorder=1)
        ax.scatter([i], [st.median(d)], color=INK, s=34, zorder=3)
        ax.scatter([i], [pc(d, 99)], color=TEAL, s=34, zorder=3, marker="D")
        ax.text(i + 0.24, pc(d, 99) + 45, f"p99 {pc(d, 99):.0f}", fontsize=8.5, color=TEAL, va="center")
        ax.text(i + 0.24, st.median(d), f"median {st.median(d):.0f}", fontsize=8.5, color=INK, va="center")
        if gw[r]:
            g = gw[r]
            ax.text(i - 0.24, 150, f"gateway out\np99 {pc(g, 99):.0f}", fontsize=7.5, color=GREY, va="bottom", ha="right")
    ax.axhline(1000, color=TEAL, lw=1, ls="--")
    ax.text(0.5, 975, "1 s: RR 1 fastest sampling (seconds)", color=TEAL, fontsize=8.5, ha="center", va="top")
    ax.set_xticks(list(x), [f"{r:g}/s\n({len(by[r])} msgs timed)" for r in rates])
    ax.set_xlabel("messages a second from one device (each = 2 readings)")
    ax.set_ylabel("device → database, ms")
    ax.set_xlim(-0.5, len(rates) - 0.1)
    ax.set_ylim(0, 1300)
    ax.set_title("E2  Device-to-database delay: almost all of it is the historian's 1 s batch window")
    note(fig, "Grey dots: individual messages (up to 600 a rate shown). Three repeats pooled; at 1/s the delay is either ~0 or ~1 s depending on where a message falls in the batch window. Commit time from PostgreSQL track_commit_timestamp. Source: results/e2_per_reading.csv")
    fig.tight_layout()
    fig.savefig(FIG / "e2_latency.png")


# --- E3 ------------------------------------------------------------------------------------------
def e3():
    s = rows("e3_summary.csv")
    fig, (ax, bx) = plt.subplots(1, 2, figsize=(10.5, 4.2))
    off = [float(r["offered_msg_s"]) for r in s]
    sto = [float(r["stored_msg_s"]) for r in s]
    lim = max(off + sto) * 1.1
    ax.plot([0, lim], [0, lim], color=LIGHT, lw=1)
    ax.text(lim * 0.6, lim * 0.64, "stored = sent", color=GREY, fontsize=8.5, rotation=0)
    ax.scatter(off, sto, color=TEAL, s=30, zorder=3)
    for r in s:
        lost = int(r["lost"])
        if lost:
            pct_lost = 100 * lost / int(r["sent"])
            ax.annotate(f"{pct_lost:.0f}% lost", (float(r["offered_msg_s"]), float(r["stored_msg_s"])),
                        textcoords="offset points", xytext=(8, 0), fontsize=8, color=TEAL, ha="left", va="center")
    knee = max(float(r["offered_msg_s"]) for r in s if not int(r["lost"]))
    ax.axvline(knee, color=TEAL, lw=1, ls="--")
    ax.text(knee * 0.97, lim * 0.93, f"sustained: {knee:,.0f} msg/s\n= {2 * knee:,.0f} readings/s", color=TEAL, fontsize=8.5, ha="right", va="top")
    ax.scatter([float(r["offered_msg_s"]) for r in s if int(r["lost"])], [float(r["stored_msg_s"]) for r in s if int(r["lost"])],
               color=INK, s=30, zorder=4)
    ax.set_xlabel("messages a second sent (achieved)")
    ax.set_ylabel("messages a second stored")
    ax.set_xlim(0, lim * 1.15)
    ax.set_ylim(0, lim)
    ax.set_title("Messages stored vs sent")
    fig.suptitle("E3  Throughput: no loss up to 2,000 messages a second, then the gateway drops readings",
                 x=0.0, ha="left", fontsize=12, fontweight="semibold")
    procs = [("broker", "broker"), ("gateway", "gateway"), ("historian", "historian")]
    tr = [float(r["target_rate"]) for r in s]
    rates = sorted(set(tr))
    for k, label in procs:
        vals = [st.mean([float(r[f"{k}_cpu_mean"]) for r in s if float(r["target_rate"]) == rr and r[f"{k}_cpu_mean"]]) for rr in rates]
        col = TEAL if k == "historian" else (INK if k == "gateway" else GREY)
        bx.plot(rates, vals, color=col, lw=2, marker="o", ms=4)
        bx.text(rates[-1] + 80, vals[-1], label, color=col, fontsize=9, va="center")
    bx.axhline(100, color=LIGHT, lw=1, ls="--")
    bx.text(0, 103, "100% = one core (Python services use one core each)", fontsize=8, color=GREY)
    bx.set_xticks([0, 1000, 2000, 3000, 4000])
    bx.set_xlim(0, rates[-1] * 1.25)
    bx.set_xlabel("messages a second (target)")
    bx.set_ylabel("CPU, % of one core")
    bx.set_title("CPU per service")
    note(fig, "Two repeats. One device; load generator on the same 2 cores, so above ~2,000 msg/s the box itself is full. Lost = temperature readings never stored. Source: results/e3_summary.csv")
    fig.tight_layout()
    fig.savefig(FIG / "e3_throughput.png")


# --- E4 ------------------------------------------------------------------------------------------
def e4():
    r = rows("e4_resilience.csv")
    fig, ax = plt.subplots(figsize=(10, 0.55 * len(r) + 1.2))
    names = [x["scenario"] for x in r][::-1]
    lost = [float(x["lost"]) for x in r][::-1]
    sent = [float(x["sent"]) for x in r][::-1]
    rec = [x["recovery_s"] for x in r][::-1]
    y = range(len(names))
    ax.barh(y, sent, color=FAINT, height=0.6)
    ax.barh(y, lost, color=[TEAL if l > 0 else INK for l in lost], height=0.6)
    for yi, l, s_, rc in zip(y, lost, sent, rec):
        txt = (f"{l:.0f} of {s_:.0f} lost" if l else f"0 of {s_:.0f} lost") + (f",  back to normal {float(rc):.0f} s after" if rc and float(rc) > 0 else "")
        ax.text(s_ + 10, yi, txt, va="center", fontsize=8.5, color=TEAL if l else INK)
    ax.set_yticks(list(y), names, fontsize=9)
    ax.set_xlim(0, max(sent) * 1.45)
    ax.set_xlabel("messages sent during the scenario (grey); lost (teal)")
    ax.grid(axis="y", visible=False)
    ax.set_title("E4  Failures injected at 10 messages a second: readings lost")
    note(fig, "Duplicate rows in every scenario: " + ", ".join(sorted(set(x["duplicate_rows"] for x in r))) + ".  Source: results/e4_resilience.csv")
    fig.tight_layout()
    fig.savefig(FIG / "e4_resilience.png")


# --- E5 ------------------------------------------------------------------------------------------
def e5():
    q = rows("e5_queries.csv")
    ranges = ["24 h", "7 d", "30 d", "365 d"]
    queries = list(dict.fromkeys(r["query"] for r in q))
    fig, ax = plt.subplots(figsize=(10, 4.8))
    x = range(len(ranges))
    ends = {}
    for n in queries:
        vals = [float(next(r["median_ms"] for r in q if r["query"] == n and r["range"] == rg)) for rg in ranges]
        flat = "Energy" in n or "quality" in n                      # same cost whatever the range
        col = TEAL if flat else (INK if "all 8" in n else LIGHT)
        ax.plot(list(x), vals, color=col, lw=2 if col != LIGHT else 1.4, marker="o", ms=4)
        ends[n] = (vals[-1], col)
    # labels at the right, nudged apart so none overlap (log scale: keep a 1.3x gap)
    placed = []
    for n, (v, col) in sorted(ends.items(), key=lambda kv: kv[1][0]):
        y = v if not placed or v / placed[-1] >= 1.45 else placed[-1] * 1.45
        placed.append(y)
        ax.text(len(ranges) - 1 + 0.08, y, n + ("  (same cost at any range)" if col == TEAL else ""), fontsize=8,
                color=col if col != LIGHT else GREY, va="center")
    for lim, label in ((1000, "1 s: flow of thought kept"), (10000, "10 s: attention lost")):
        ax.hlines(lim, -0.2, len(ranges) - 1, color=TEAL, lw=1, ls="--")
        ax.text(0, lim * 1.08, label + " (Nielsen)", fontsize=8, color=TEAL)
    ax.set_yscale("log")
    ax.set_xticks(list(x), ranges)
    ax.set_xlim(-0.2, len(ranges) + 1.6)
    ax.set_xlabel("dashboard time range")
    ax.set_ylabel("query time, ms (median of 5)")
    ax.set_title("E5  Dashboard queries on one year of data (10 points × 1/min, plain PostgreSQL)")
    note(fig, "No TimescaleDB here: the hourly mean is computed from raw rows, which a continuous aggregate would avoid. Source: results/e5_queries.csv")
    fig.tight_layout()
    fig.savefig(FIG / "e5_queries.png")


if __name__ == "__main__":
    for name in sys.argv[1:] or ["e1", "e2", "e3", "e4", "e5"]:
        globals()[name]()
        print("drew", name)
