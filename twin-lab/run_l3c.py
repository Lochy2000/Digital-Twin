"""L3c: the 1R1C twin with all heat sources, against the BOPTEST recording.

Draws measured vs predicted zone temperature, with the residual underneath,
and prints the average error. Run from twin-lab:  python run_l3c.py
Saves l3c_twin_vs_plant.png.
"""

import matplotlib.pyplot as plt

from twinlab.data import load_timesteps
from twinlab.loop import run_open_loop
from twinlab.metrics import mae, residuals, rmse
from twinlab.rc1 import RC1

# Still guesses (NOTES.md, L3b). L3d fits all three from the data.
R = 0.02            # K/W
C = 3e6             # J/K
SOLAR_AREA = 5.0    # m2, effective sun-catching area

moments = load_timesteps("data/boptest_bestest_air.csv")
model = RC1(R=R, C=C, solar_area_m2=SOLAR_AREA)
predicted = run_open_loop(model, moments)
measured = [m["unit1.zone_air_temp"] for m in moments]
res = residuals(measured, predicted)

print(f"R = {R} K/W, C = {C:.0e} J/K, solar area = {SOLAR_AREA} m2")
print(f"MAE  {mae(res):.2f} °C   (average size of the miss)")
print(f"RMSE {rmse(res):.2f} °C   (big misses count extra)")

times = [m["time"] for m in moments]
fig, (top, bottom) = plt.subplots(2, 1, sharex=True, figsize=(9, 6), gridspec_kw={"height_ratios": [3, 2]})
top.plot(times, measured, color="black", label="measured (BOPTEST)")
top.plot(times, predicted, color="tab:red", label="predicted (1R1C twin)")
top.plot(times, [m["weather1.outside_air_temp"] for m in moments], color="grey", linestyle="--", label="outside")
top.set_ylabel("°C")
top.legend(frameon=False, loc="lower left")
bottom.axhline(0, color="grey", linewidth=0.8)
bottom.plot(times, res, color="tab:red")
bottom.set_ylabel("residual °C\n(measured − predicted)")
for ax in (top, bottom):
    ax.spines[["top", "right"]].set_visible(False)
fig.tight_layout()
fig.savefig("l3c_twin_vs_plant.png", dpi=110)
print("saved l3c_twin_vs_plant.png")
