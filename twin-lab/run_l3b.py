"""L3b: run the 1R1C twin (open loop) through the BOPTEST recording.

Prints measured vs predicted zone temperature every 3 hours.
Run from twin-lab:  python run_l3b.py
"""

from twinlab.data import load_timesteps
from twinlab.loop import run_open_loop
from twinlab.rc1 import RC1

# Rough guesses read off the recording (workings in NOTES.md, L3b).
# L3d replaces these with fitted values.
R = 0.02   # K/W  -> the room loses about 50 W per °C of difference
C = 3e6    # J/K  -> time constant R*C = 60,000 s, about 17 hours

moments = load_timesteps("data/boptest_bestest_air.csv")
predicted = run_open_loop(RC1(R=R, C=C), moments)

print(f"R = {R} K/W, C = {C:.0e} J/K, time constant {R * C / 3600:.0f} h\n")
print("time           measured °C  predicted °C")
for m, p in list(zip(moments, predicted))[11::12]:   # every 12th moment = every 3 h
    print(f"{m['time']:%d %b %H:%M}   {m['unit1.zone_air_temp']:10.2f}  {p:12.2f}")
