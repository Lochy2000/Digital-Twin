"""Checks the fit can recover values we already know.

We make a fake recording with a 1R1C model whose values we choose, then ask
fit_rc1 to find them starting from wrong guesses. If it gets back to the
values we chose, the fitting works. (On BOPTEST data there are no "true"
values to compare against, which is why this check uses fake data.)
"""

import math
from datetime import datetime, timedelta, timezone

import pytest

from twinlab.fit import fit_rc1
from twinlab.loop import model_inputs
from twinlab.rc1 import RC1


def fake_recording(model, hours=48):
    t0 = datetime(2026, 1, 15, tzinfo=timezone.utc)
    moments, state = [], {"zone_temp_C": 15.0}
    for i in range(hours * 4):  # every 15 minutes
        h = (i / 4) % 24
        m = {
            "time": t0 + timedelta(minutes=15 * i),
            "unit1.zone_air_temp": state["zone_temp_C"],
            "weather1.outside_air_temp": -3 + 5 * math.sin(2 * math.pi * (h - 9) / 24),
            "unit1.heat_output": 2.0 if 7 <= h < 17 else 0.3,
            "unit1.cool_power": 0.0,
            "zone1.lighting_power": 0.3 if 8 <= h < 18 else 0.03,
            "zone1.plug_power": 0.1,
            "weather1.solar_global": max(0.0, 500 * math.sin(math.pi * (h - 7) / 10)) if 7 <= h < 17 else 0.0,
        }
        moments.append(m)
        state = model.step(state, model_inputs(m), 900)
    return moments


def test_fit_recovers_known_values_from_wrong_guesses():
    true = RC1(R=0.015, C=4e6, solar_area_m2=3.0)
    fitted = fit_rc1([fake_recording(true)], start=(0.03, 1e6, 8.0))
    assert fitted.R == pytest.approx(0.015, rel=0.01)
    assert fitted.C == pytest.approx(4e6, rel=0.01)
    assert fitted.solar_area_m2 == pytest.approx(3.0, rel=0.01)


def test_values_not_named_in_fit_stay_fixed():
    true = RC1(R=0.015, C=4e6, solar_area_m2=3.0)
    fitted = fit_rc1([fake_recording(true)], start=(0.015, 4e6, 8.0), fit=("solar_area",))
    assert fitted.R == 0.015 and fitted.C == 4e6           # untouched
    assert fitted.solar_area_m2 == pytest.approx(3.0, rel=0.01)


def test_several_segments_each_restart_from_their_own_measurement():
    true = RC1(R=0.015, C=4e6, solar_area_m2=3.0)
    rec = fake_recording(true)
    halves = [rec[:96], rec[96:]]                           # two separate days
    fitted = fit_rc1(halves, start=(0.03, 1e6, 8.0))
    assert fitted.R == pytest.approx(0.015, rel=0.01)
    assert fitted.C == pytest.approx(4e6, rel=0.01)


def test_fixing_the_time_constant_keeps_r_times_c():
    true = RC1(R=0.015, C=4e6, solar_area_m2=3.0)          # time constant 60,000 s
    fitted = fit_rc1([fake_recording(true)], start=(0.03, 1e6, 8.0),
                     fit=("R", "solar_area"), tau_s=60_000)
    assert fitted.time_constant_s == pytest.approx(60_000)
    assert fitted.R == pytest.approx(0.015, rel=0.01)       # and R is still found
