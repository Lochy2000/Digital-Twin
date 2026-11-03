"""Draw a recorded plant CSV: temperatures, heating/cooling and sunshine.

    python plot_plant.py                                  (default file)
    python plot_plant.py data/boptest_bestest_air.csv

Saves a PNG next to the CSV with the same name.
"""

import csv
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import matplotlib.pyplot as plt

path = Path(sys.argv[1] if len(sys.argv) > 1 else "data/boptest_bestest_air.csv")

# Read the canonical rows into one (times, values) series per point.
series = defaultdict(lambda: ([], []))
for row in csv.DictReader(path.open()):
    t = datetime.fromisoformat(row["sensor_time"].replace("Z", "+00:00"))
    series[row["point"]][0].append(t)
    series[row["point"]][1].append(float(row["value"]))

fig, ax = plt.subplots(3, 1, sharex=True, figsize=(9, 7), gridspec_kw={"height_ratios": [3, 2, 2]})
ax[0].plot(*series["unit1.zone_air_temp"], color="black", label="zone")
ax[0].plot(*series["weather1.outside_air_temp"], color="grey", linestyle="--", label="outside")
ax[0].set_ylabel("°C")
ax[1].plot(*series["unit1.heat_output"], color="tab:red", label="heating (heat delivered)")
ax[1].plot(*series["unit1.cool_power"], color="tab:blue", label="cooling (electricity used)")
ax[1].set_ylabel("kW")
ax[2].plot(*series["weather1.solar_global"], color="tab:orange", label="sunshine")
ax[2].set_ylabel("W/m²")
for a in ax:
    a.legend(frameon=False)
    a.spines[["top", "right"]].set_visible(False)
fig.tight_layout()
out = path.with_suffix(".png")
fig.savefig(out, dpi=110)
print(f"saved {out}")
