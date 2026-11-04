"""Fitting the 1R1C model's values (R, C, sun area) to recorded data.

The idea ("least squares")
--------------------------
Pick some R, C and sun area, run the twin through the data, and work out the
residual at every moment. Square each residual and add them up: a single
number that is small when the twin follows the room well. SciPy's
`least_squares` then tries value after value, each time moving in the
direction that makes that number smaller, until it can't improve any more.
That's all "fitting" or "calibration" means here.

Segments (L3e)
--------------
The data is given as a list of *segments*: separate stretches of time, e.g.
each night's cool-down. The twin is restarted from the measured temperature
at the start of each segment, so a gap between segments (daytime, here) never
counts against it. A single long recording is just one segment.

Choosing what to fit (L3e)
--------------------------
`fit=` says which values SciPy may change; the others stay at their `start`
value. That's what allows fitting in stages: the time constant on night
cool-downs first (no sun, so the sun area can't trade off against it), then
R and the sun area on whole days with the time constant fixed.

Fixing the time constant (L3e)
------------------------------
A cool-down only shows how *fast* the room cools: the time constant R x C.
It can't tell a small R with a big C from a big R with a small C (RR 1 §7:
the decay "yields the time constant", and a heat input is needed to separate
R and C). So `tau_s=` can fix R x C: C is then worked out as tau / R instead
of being fitted.

Two practical details
---------------------
- R (about 0.02) and C (about 3,000,000) are wildly different sizes. SciPy is
  given log(R) and log(C) instead, which puts them on a similar scale and
  also means R and C can never go negative (exp of anything is positive).
- The sun area is searched directly, with a lower limit of 0.
"""

import math

from scipy.optimize import least_squares

from twinlab.loop import run_open_loop
from twinlab.metrics import residuals
from twinlab.rc1 import RC1

ALL = ("R", "C", "solar_area")


def segment_residuals(model, segments: list[list[dict]]) -> list[float]:
    """Run the model open loop over each segment; return all residuals together."""
    out = []
    for seg in segments:
        measured = [m["unit1.zone_air_temp"] for m in seg]
        out += residuals(measured, run_open_loop(model, seg))
    return out


def fit_rc1(segments: list[list[dict]], start=(0.02, 3e6, 5.0), fit=ALL, tau_s=None) -> RC1:
    """Return an RC1 with the values named in `fit` fitted; the rest kept at `start`.

    If `tau_s` is given, C is always tau_s / R (so "C" mustn't be in `fit`).
    """
    if tau_s is not None and "C" in fit:
        raise ValueError("with tau_s fixed, C follows from R; don't fit C as well")
    values = dict(zip(ALL, start))

    # SciPy works on a plain list of numbers; these two helpers convert.
    def to_x(v):
        return [math.log(v[k]) if k in ("R", "C") else v[k] for k in fit]

    def model_from(x):
        v = dict(values)
        for k, xi in zip(fit, x):
            v[k] = math.exp(xi) if k in ("R", "C") else xi
        if tau_s is not None:
            v["C"] = tau_s / v["R"]
        return RC1(R=v["R"], C=v["C"], solar_area_m2=v["solar_area"])

    lower = [0.0 if k == "solar_area" else -math.inf for k in fit]
    # least_sqaures optimizer sqaures all errors and sums them into a pentalty score. it then automatically adjusts R, C, and solar_area to minimize the penalty score. the result is a set of parameters that best fit the measured data.
    result = least_squares(lambda x: segment_residuals(model_from(x), segments),
                           x0=to_x(values), bounds=(lower, [math.inf] * len(fit)))
    if not result.success:
        raise RuntimeError(f"fit didn't converge: {result.message}")
    return model_from(result.x)
