"""Checks the Luenberger observer: predict, compare, correct."""

from datetime import datetime, timedelta, timezone

import pytest

from twinlab.loop import model_inputs, run_open_loop
from twinlab.observer import LuenbergerObserver
from twinlab.rc1 import RC1

T0 = datetime(2026, 1, 15, tzinfo=timezone.utc)
MODEL = RC1(R=0.02, C=3e6, solar_area_m2=5.0)


def moment(minutes, zone, outside=-5.0, heat_kW=0.5):
    return {"time": T0 + timedelta(minutes=minutes), "unit1.zone_air_temp": zone,
            "weather1.outside_air_temp": outside, "unit1.heat_output": heat_kW,
            "unit1.cool_power": 0.0, "zone1.lighting_power": 0.1,
            "zone1.plug_power": 0.05, "weather1.solar_global": 0.0}


MOMENTS = [moment(15 * i, zone) for i, zone in enumerate([20.0, 20.5, 21.0, 20.2, 19.8])]


def test_gain_zero_is_the_same_as_open_loop():
    records = LuenbergerObserver(MODEL, gain=0.0).run(MOMENTS)
    assert [r["predicted"] for r in records] == pytest.approx(run_open_loop(MODEL, MOMENTS))


def test_gain_one_jumps_to_each_measurement():
    records = LuenbergerObserver(MODEL, gain=1.0).run(MOMENTS)
    assert [r["corrected"] for r in records] == pytest.approx([m["unit1.zone_air_temp"] for m in MOMENTS])


def test_one_step_worked_by_hand():
    # Step 1 from 20.0 °C: predict with the model, then move 30% of the way to 20.5.
    predicted = MODEL.step({"zone_temp_C": 20.0}, model_inputs(MOMENTS[0]), 900)["zone_temp_C"]
    r = LuenbergerObserver(MODEL, gain=0.3).run(MOMENTS)[1]
    assert r["predicted"] == pytest.approx(predicted)
    assert r["residual"] == pytest.approx(20.5 - predicted)
    assert r["corrected"] == pytest.approx(predicted + 0.3 * (20.5 - predicted))


def test_missing_measurement_means_no_correction():
    moments = [MOMENTS[0], {**MOMENTS[1], "unit1.zone_air_temp": None}]
    r = LuenbergerObserver(MODEL, gain=0.5).run(moments)[1]
    assert r["residual"] is None
    assert r["corrected"] == r["predicted"]       # coasted on the prediction


def test_gain_outside_0_to_1_is_refused():
    with pytest.raises(ValueError):
        LuenbergerObserver(MODEL, gain=1.5)
