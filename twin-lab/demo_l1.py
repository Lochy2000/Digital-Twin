"""L1 demo: run the 1R1C model through one made-up winter day and draw it.

No sensors and no twin loop yet: this only shows what the model on its own
predicts. Run from the twin-lab folder:  python demo_l1.py
"""

import matplotlib.pyplot as plt

from twinlab.rc1 import RC1

# Placeholder values (not Botanic's unit): see tests/test_rc1.py
model = RC1(R=0.005, C=5e6)

OUTSIDE_C = 5.0          # constant, to keep it simple
UNIT_W = 5000            # unit heating at 5 kW ...
ON_HOURS = range(7, 17)  # ... from 07:00 to 17:00 (production hours)
DT = 60                  # one step a minute

state = model.initial_state({"zone_temp_C": 12.0})
hours, temps, heat = [], [], []
for minute in range(24 * 60):
    hour = minute / 60
    q = UNIT_W if int(hour) in ON_HOURS else 0
    hours.append(hour)
    temps.append(model.predict(state)["zone_temp_C"])
    heat.append(q / 1000)
    state = model.step(state, {"outside_temp_C": OUTSIDE_C, "unit_heat_W": q}, DT)

print(f"time constant: {model.time_constant_s / 3600:.1f} h")
for h in (0, 7, 12, 17, 23):
    print(f"{h:02d}:00  zone {temps[h * 60]:5.1f} °C   unit {heat[h * 60]:.0f} kW")

fig, (ax1, ax2) = plt.subplots(2, 1, sharex=True, figsize=(8, 5),
                               gridspec_kw={"height_ratios": [3, 1]})
ax1.plot(hours, temps, color="black", label="zone (model)")
ax1.axhline(OUTSIDE_C, color="grey", linestyle="--", label="outside")
ax1.set_ylabel("°C")
ax1.legend(frameon=False)
ax2.step(hours, heat, where="post", color="tab:red")
ax2.set_ylabel("unit kW")
ax2.set_xlabel("hour of day")
ax2.set_xticks(range(0, 25, 3))
for ax in (ax1, ax2):
    ax.spines[["top", "right"]].set_visible(False)
fig.tight_layout()
fig.savefig("demo_l1.png", dpi=120)
print("saved demo_l1.png")
