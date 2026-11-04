"""L4: the 1R1C twin with a Luenberger observer, on the 14-day recording.

Part 1: how the residual changes with the observer gain L.
Part 2: the catch. Make the sensor suddenly read 2 °C too high (a lasting
        fault) and see how long the residual keeps showing it for each gain.
Run from twin-lab:  python run_l4.py   (needs data/boptest_14days.csv)
Saves l4_observer.png.
"""

import matplotlib.pyplot as plt

from twinlab.data import load_timesteps
from twinlab.metrics import mae
from twinlab.observer import LuenbergerObserver
from twinlab.rc1 import RC1

# Values from the staged fit in L3e (run_l3e.py).
model = RC1(R=0.0114, C=8.23e6, solar_area_m2=12.12)
moments = load_timesteps("data/boptest_14days.csv")

# ---- Part 1: residual size for different gains -------------------------------
print("Part 1: healthy data, 14 days")
print("gain L   residual MAE   steps with |residual| > 1 °C")
for gain in (0.0, 0.05, 0.1, 0.2, 0.3, 0.5, 1.0):
    res = [r["residual"] for r in LuenbergerObserver(model, gain).run(moments)[1:]]
    print(f"{gain:5.2f}   {mae(res):9.2f} °C   {sum(abs(x) > 1 for x in res):8d} of {len(res)}")

# ---- Part 2: a lasting sensor fault -----------------------------------------
# 02:00 on 26 Jan: a quiet time, when the healthy residual is near zero,
# so the fault isn't mixed up with the 08:00 jump.
FAULT_AT = next(i for i, m in enumerate(moments) if m["time"].strftime("%d %H:%M") == "26 02:00")
faulty = [dict(m) for m in moments]
for m in faulty[FAULT_AT:]:
    m["unit1.zone_air_temp"] += 2.0  # sensor now reads 2 °C high, from here on

print("\nPart 2: sensor reads 2 °C high from", faulty[FAULT_AT]["time"])
print("gain L   residual straight after   time until residual is back under 1 °C")
runs = {}
for gain in (0.05, 0.1, 0.3, 0.5):
    records = LuenbergerObserver(model, gain).run(faulty)
    runs[gain] = records
    after = [r["residual"] for r in records[FAULT_AT:]]
    steps = next((k for k, x in enumerate(after) if x < 1.0), len(after))
    print(f"{gain:5.2f}   {after[0]:12.2f} °C            {steps / 4:5.2f} h")

# ---- Chart -------------------------------------------------------------------
fig, (top, bottom) = plt.subplots(2, 1, figsize=(9, 7))
times = [m["time"] for m in moments]
for gain, colour in ((0.0, "lightgrey"), (0.2, "tab:red")):
    res = [r["residual"] for r in LuenbergerObserver(model, gain).run(moments)]
    label = "open loop (L = 0)" if gain == 0 else f"observer, L = {gain}"
    top.plot(times, res, color=colour, label=label, linewidth=1)
top.axhline(0, color="grey", linewidth=0.8)
top.set_ylabel("residual °C")
top.set_title("Healthy data: the observer keeps the residual near zero", loc="left", fontsize=10)
top.legend(frameon=False)

window = slice(FAULT_AT - 8, FAULT_AT + 22)            # 2 h before to 5.5 h after (before 08:00)
for gain, colour in ((0.05, "tab:blue"), (0.5, "tab:orange")):
    recs = runs[gain][window]
    bottom.plot([r["time"] for r in recs], [r["residual"] for r in recs], color=colour, label=f"L = {gain}")
bottom.axvline(faulty[FAULT_AT]["time"], color="black", linestyle=":", label="sensor starts reading 2 °C high")
bottom.axhline(0, color="grey", linewidth=0.8)
bottom.set_ylabel("residual °C")
bottom.set_title("A lasting fault: a big gain absorbs it within minutes", loc="left", fontsize=10)
bottom.legend(frameon=False)
for ax in (top, bottom):
    ax.spines[["top", "right"]].set_visible(False)
fig.tight_layout()
fig.savefig("l4_observer.png", dpi=110)
print("\nsaved l4_observer.png")
