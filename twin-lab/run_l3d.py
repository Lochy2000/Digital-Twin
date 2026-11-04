"""L3d: fit R, C and sun area on days 1-2, then check on day 3 (never seen by the fit).

Run from twin-lab:  python run_l3d.py
Prints guessed vs fitted values and errors; saves l3d_fitted.png.
"""

import matplotlib.pyplot as plt

from twinlab.data import load_timesteps
from twinlab.fit import fit_rc1
from twinlab.loop import run_open_loop
from twinlab.metrics import mae, residuals, rmse
from twinlab.rc1 import RC1

moments = load_timesteps("data/boptest_bestest_air.csv")
split = 2 * 96                      # 96 moments a day at 15 minutes
train, test = moments[:split], moments[split:]


def errors(model, part):
    """Run open loop over one part (starting from its own first measurement)."""
    measured = [m["unit1.zone_air_temp"] for m in part]
    predicted = run_open_loop(model, part)
    res = residuals(measured, predicted)
    return predicted, res, mae(res), rmse(res)


guess = RC1(R=0.02, C=3e6, solar_area_m2=5.0)
fitted = fit_rc1([train])

print("                 R (K/W)   C (MJ/K)   sun area (m2)   time constant")
for name, m in (("guessed (L3c)", guess), ("fitted on days 1-2", fitted)):
    print(f"{name:18s} {m.R:7.4f}   {m.C / 1e6:7.2f}    {m.solar_area_m2:8.2f}        {m.time_constant_s / 3600:5.1f} h")

print("\n                    MAE days 1-2   MAE day 3 (unseen)   RMSE day 3")
for name, m in (("guessed (L3c)", guess), ("fitted on days 1-2", fitted)):
    _, _, mae_train, _ = errors(m, train)
    _, _, mae_test, rmse_test = errors(m, test)
    print(f"{name:18s}  {mae_train:9.2f} °C   {mae_test:13.2f} °C     {rmse_test:6.2f} °C")

# Chart: fitted twin over all three days, the unseen day shaded.
pred_train, res_train, *_ = errors(fitted, train)
pred_test, res_test, *_ = errors(fitted, test)
times = [m["time"] for m in moments]
fig, (top, bottom) = plt.subplots(2, 1, sharex=True, figsize=(9, 6), gridspec_kw={"height_ratios": [3, 2]})
top.plot(times, [m["unit1.zone_air_temp"] for m in moments], color="black", label="measured (BOPTEST)")
top.plot(times, pred_train + pred_test, color="tab:red", label="predicted (fitted 1R1C)")
top.set_ylabel("°C")
top.legend(frameon=False, loc="lower left")
bottom.axhline(0, color="grey", linewidth=0.8)
bottom.plot(times, res_train + res_test, color="tab:red")
bottom.set_ylabel("residual °C")
for ax in (top, bottom):
    ax.axvspan(test[0]["time"], test[-1]["time"], color="grey", alpha=0.12)
    ax.spines[["top", "right"]].set_visible(False)
top.text(test[0]["time"], top.get_ylim()[1], "  day 3: not used for fitting", va="top", fontsize=9, color="dimgrey")
fig.tight_layout()
fig.savefig("l3d_fitted.png", dpi=110)
print("\nsaved l3d_fitted.png")
