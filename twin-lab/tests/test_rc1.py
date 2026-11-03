"""Checks the 1R1C model against answers worked out by hand."""

import math

import pytest

from twinlab.rc1 import RC1

# Placeholder zone: loses 200 W per degree of difference (R = 1/200 K/W),
# stores 5 MJ per degree (C = 5e6 J/K). Time constant = 25,000 s (~7 h).
R, C = 0.005, 5e6


def test_time_constant():
    assert RC1(R, C).time_constant_s == pytest.approx(25_000)


def test_one_time_constant_closes_63_percent_of_the_gap():
    # Unit off, zone 20 °C, outside 0 °C: after R*C seconds the zone should be
    # 20 * exp(-1) = 7.36 °C (63% of the way to outside).
    m = RC1(R, C)
    s = m.step({"zone_temp_C": 20.0}, {"outside_temp_C": 0.0, "unit_heat_W": 0.0}, 25_000)
    assert s["zone_temp_C"] == pytest.approx(20 * math.exp(-1))


def test_heating_settles_at_the_balance_temperature():
    # 5 kW in, outside 5 °C: balance = 5 + 0.005 * 5000 = 30 °C.
    m = RC1(R, C)
    s = m.step({"zone_temp_C": 15.0}, {"outside_temp_C": 5.0, "unit_heat_W": 5000}, 1e7)
    assert s["zone_temp_C"] == pytest.approx(30.0)


def test_cooling_is_negative_heat():
    # 2 kW of cooling, outside 30 °C: balance = 30 - 0.005 * 2000 = 20 °C.
    m = RC1(R, C)
    s = m.step({"zone_temp_C": 28.0}, {"outside_temp_C": 30.0, "unit_heat_W": -2000}, 1e7)
    assert s["zone_temp_C"] == pytest.approx(20.0)


def test_uneven_steps_give_the_same_answer_as_one_big_step():
    # The twin steps by the real time between readings, which varies.
    # 60 s + 7 s + 233 s must equal one 300 s step.
    m = RC1(R, C)
    u = {"outside_temp_C": 5.0, "unit_heat_W": 3000}
    one = m.step({"zone_temp_C": 18.0}, u, 300)
    s = {"zone_temp_C": 18.0}
    for dt in (60, 7, 233):
        s = m.step(s, u, dt)
    assert s["zone_temp_C"] == pytest.approx(one["zone_temp_C"])


def test_zero_dt_changes_nothing():
    m = RC1(R, C)
    s = m.step({"zone_temp_C": 18.0}, {"outside_temp_C": 5.0, "unit_heat_W": 3000}, 0)
    assert s["zone_temp_C"] == 18.0


def test_step_does_not_change_the_state_it_was_given():
    # Needed for what-if runs: they start from the live state and must not alter it.
    m = RC1(R, C)
    live = {"zone_temp_C": 18.0}
    m.step(live, {"outside_temp_C": 5.0, "unit_heat_W": 3000}, 600)
    assert live == {"zone_temp_C": 18.0}


def test_bad_values_are_refused():
    with pytest.raises(ValueError):
        RC1(0, C)
    with pytest.raises(ValueError):
        RC1(R, C).step({"zone_temp_C": 18.0}, {"outside_temp_C": 5.0, "unit_heat_W": 0}, -1)


def test_internal_gains_and_sun_add_heat_like_the_unit_does():
    # 1 kW from the unit, or 400 W of lights + 200 W/m2 sun on 3 m2: same 1 kW in total,
    # so both settle at the same balance temperature: 5 + 0.005 * 1000 = 10 °C.
    m = RC1(R, C, solar_area_m2=3)
    unit_only = m.step({"zone_temp_C": 5.0}, {"outside_temp_C": 5.0, "unit_heat_W": 1000}, 1e7)
    gains = m.step({"zone_temp_C": 5.0}, {"outside_temp_C": 5.0, "unit_heat_W": 0,
                                          "internal_gain_W": 400, "solar_W_m2": 200}, 1e7)
    assert unit_only["zone_temp_C"] == pytest.approx(10.0)
    assert gains["zone_temp_C"] == pytest.approx(10.0)
