"""L3b follow-up: why does the open-loop twin drift so far? A quick experiment.

1. Energy balance: how much heat the room loses on average vs what the unit gives.
2. Re-run the twin with extra heat sources added, and compare the average error.

The sun term uses an "effective area": sunshine (W/m2) x area (m2) = watts in.
It's a made-up number to try here; L3d fits it properly.
Run from twin-lab:  python explore_l3b_gains.py
"""

from twinlab.data import load_timesteps
from twinlab.loop import unit_heat_W
from twinlab.rc1 import RC1

R, C = 0.02, 3e6
moments = load_timesteps("data/boptest_bestest_air.csv")
n = len(moments)


def average(fn):
    return sum(fn(m) for m in moments) / n


temp_diff = average(lambda m: m["unit1.zone_air_temp"] - m["weather1.outside_air_temp"])
print(f"Average inside - outside: {temp_diff:.1f} °C -> with R = {R} the room loses about {temp_diff / R:.0f} W")
print(f"Average heat in: unit (net) {average(unit_heat_W):.0f} W, "
      f"lights {1000 * average(lambda m: m['zone1.lighting_power']):.0f} W, "
      f"plugs {1000 * average(lambda m: m['zone1.plug_power']):.0f} W, "
      f"sunshine {average(lambda m: m['weather1.solar_global']):.0f} W/m2\n")


def mean_abs_error(extra_heat_W):
    """Run the twin open loop with extra heat added; return the average |measured - predicted|."""
    model = RC1(R, C)
    state = {"zone_temp_C": moments[0]["unit1.zone_air_temp"]}
    errors = []
    for prev, now in zip(moments, moments[1:]):
        heat = unit_heat_W(prev) + extra_heat_W(prev)
        dt = (now["time"] - prev["time"]).total_seconds()
        state = model.step(state, {"outside_temp_C": prev["weather1.outside_air_temp"], "unit_heat_W": heat}, dt)
        errors.append(abs(now["unit1.zone_air_temp"] - state["zone_temp_C"]))
    return sum(errors) / len(errors)


def internal(m):
    return 1000 * (m["zone1.lighting_power"] + m["zone1.plug_power"])


print("Heat given to the twin                      average error")
print(f"unit only                                    {mean_abs_error(lambda m: 0):5.1f} °C")
print(f"+ lights and plugs                           {mean_abs_error(internal):5.1f} °C")
for area in (2, 4, 6):
    print(f"+ lights, plugs and sun x {area} m2              "
          f"{mean_abs_error(lambda m: internal(m) + area * m['weather1.solar_global']):5.1f} °C")
