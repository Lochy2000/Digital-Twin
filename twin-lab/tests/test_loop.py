"""Checks the open-loop twin against the 1R1C model stepped by hand."""

from datetime import datetime, timedelta, timezone

import pytest

from twinlab.loop import model_inputs, run_open_loop, unit_heat_W
from twinlab.rc1 import RC1

T0 = datetime(2026, 1, 15, tzinfo=timezone.utc)


def moment(minutes, zone, outside, heat_kW, cool_kW=0.0):
    return {"time": T0 + timedelta(minutes=minutes), "unit1.zone_air_temp": zone,
            "weather1.outside_air_temp": outside, "unit1.heat_output": heat_kW,
            "unit1.cool_power": cool_kW}


def test_net_heat_is_heating_minus_three_times_cooling_electricity():
    assert unit_heat_W(moment(0, 20, 0, heat_kW=2.0)) == pytest.approx(2000)
    assert unit_heat_W(moment(0, 20, 0, heat_kW=0.0, cool_kW=0.5)) == pytest.approx(-1500)


def test_inputs_use_the_models_names():
    assert model_inputs(moment(0, 20, -5, heat_kW=1.0)) == {"outside_temp_C": -5, "unit_heat_W": 1000}


def test_one_prediction_per_moment_starting_from_the_first_measurement():
    moments = [moment(0, 15.0, -6, 0.5), moment(15, 99.0, -6, 0.5), moment(30, 99.0, -6, 0.5)]
    preds = run_open_loop(RC1(R=0.02, C=3e6), moments)
    assert len(preds) == 3
    assert preds[0] == 15.0          # starts from the measured value...
    assert preds[1] != 99.0          # ...then ignores later measurements (open loop)


def test_matches_stepping_the_model_by_hand_with_uneven_gaps():
    m = RC1(R=0.02, C=3e6)
    moments = [moment(0, 15.0, -6, 0.5), moment(15, 0, -5, 1.0), moment(50, 0, -4, 0.0)]
    s = {"zone_temp_C": 15.0}
    s = m.step(s, {"outside_temp_C": -6, "unit_heat_W": 500}, 15 * 60)    # inputs from moment 0
    s1 = s["zone_temp_C"]
    s = m.step(s, {"outside_temp_C": -5, "unit_heat_W": 1000}, 35 * 60)   # inputs from moment 1
    assert run_open_loop(m, moments) == pytest.approx([15.0, s1, s["zone_temp_C"]])
