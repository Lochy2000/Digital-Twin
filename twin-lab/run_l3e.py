"""L3e: fit on 10 days, check on 4 unseen days. Three ways of getting R, C and sun area.

  guessed   the L3c guesses (R 0.02, C 3 MJ/K, sun 5 m2)
  one go    all three fitted together on the 10 training days (the L3d method)
  staged    RR 1 §7's method: (1) the time constant R x C from night cool-downs,
            (2) R and sun area from the 10 training days, with R x C fixed

Each day is run on its own: the twin starts from that midnight's measured
temperature and runs open loop for 24 h.
Run from twin-lab:  python run_l3e.py   (needs data/boptest_14days.csv)
Saves l3e_unseen_days.png.
"""

import matplotlib.pyplot as plt

from twinlab.data import find_cooldowns, load_timesteps, split_days
from twinlab.fit import fit_rc1, segment_residuals
from twinlab.loop import run_open_loop
from twinlab.metrics import mae, rmse
from twinlab.rc1 import RC1

days = [d for d in split_days(load_timesteps("data/boptest_14days.csv")) if len(d) > 4]
train, test = days[:10], days[10:]
train_cooldowns = find_cooldowns([m for d in train for m in d])
test_cooldowns = find_cooldowns([m for d in test for m in d])
print(f"{len(train)} training days ({len(train_cooldowns)} night cool-downs), {len(test)} unseen days\n")

guessed = RC1(R=0.02, C=3e6, solar_area_m2=5.0)
one_go = fit_rc1(train)

# Staged, step 1: cool-downs give the time constant. R is held at 0.02 only so
# that C can be fitted; R hardly matters here, only R x C does.
step1 = fit_rc1(train_cooldowns, start=(0.02, 3e6, 0.0), fit=("C",))
tau = step1.time_constant_s
# Staged, step 2: R and sun area on whole days, with R x C fixed at tau.
staged = fit_rc1(train, start=(0.02, tau / 0.02, 5.0), fit=("R", "solar_area"), tau_s=tau)
print(f"staged step 1: night cool-downs give a time constant of {tau / 3600:.1f} h\n")

print("            R (K/W)  C (MJ/K)  sun (m2)  time const   MAE train  MAE unseen  RMSE unseen  MAE unseen nights")
for name, m in (("guessed", guessed), ("one go", one_go), ("staged", staged)):
    print(f"{name:10s} {m.R:8.4f} {m.C / 1e6:9.2f} {m.solar_area_m2:9.2f} {m.time_constant_s / 3600:9.1f} h"
          f" {mae(segment_residuals(m, train)):9.2f}   {mae(segment_residuals(m, test)):9.2f}"
          f"  {rmse(segment_residuals(m, test)):10.2f}   {mae(segment_residuals(m, test_cooldowns)):12.2f}")

# Chart: the 4 unseen days, measured vs the two fitted twins.
fig, ax = plt.subplots(figsize=(9, 4.5))
times = [m["time"] for d in test for m in d]
ax.plot(times, [m["unit1.zone_air_temp"] for d in test for m in d], color="black", label="measured (BOPTEST)")
for name, m, colour in (("one go", one_go, "tab:red"), ("staged", staged, "tab:blue")):
    ax.plot(times, [p for d in test for p in run_open_loop(m, d)], color=colour, label=f"twin, fitted {name}")
ax.set_ylabel("°C")
ax.set_title("Unseen days 25–28 Jan (each day restarted from its midnight reading)", loc="left", fontsize=10)
ax.legend(frameon=False)
ax.spines[["top", "right"]].set_visible(False)
fig.tight_layout()
fig.savefig("l3e_unseen_days.png", dpi=110)
print("\nsaved l3e_unseen_days.png")
