"""L3a: load the BOPTEST recording and print the first few moments as a table.

Nothing clever yet: this just shows what the twin will "see" at each step.
Run from twin-lab:  python look_l3a.py
"""

from twinlab.data import load_timesteps

moments = load_timesteps("data/boptest_bestest_air.csv")
print(f"{len(moments)} moments, from {moments[0]['time']} to {moments[-1]['time']}\n")

print("time               zone °C  outside °C  heating kW  cooling elec kW")
for m in moments[:8]:
    print(f"{m['time']:%d %b %H:%M}       {m['unit1.zone_air_temp']:6.2f}  "
          f"{m['weather1.outside_air_temp']:9.2f}  {m['unit1.heat_output']:10.3f}  "
          f"{m['unit1.cool_power']:14.3f}")
