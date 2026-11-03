"""Fitting the 1R1C model's values (R, C, sun area) to a recording.

The idea ("least squares")
--------------------------
Pick some R, C and sun area, run the twin through the recording, and work out
the residual at every moment. Square each residual and add them up: a single
number that is small when the twin follows the room well. SciPy's
`least_squares` then tries value after value, each time moving in the
direction that makes that number smaller, until it can't improve any more.
That's all "fitting" or "calibration" means here.

Two practical details
---------------------
- R is about 0.02 and C about 3,000,000: wildly different sizes. SciPy is
  given log(R) and log(C) instead, which puts them on a similar scale and
  also means R and C can never go negative (exp of anything is positive).
- The sun area is searched directly, with a lower limit of 0.

RR 1 §7: fit on one period, then check on a period the fit never saw. The
script `run_l3d.py` does that split.
"""

import math

from scipy.optimize import least_squares

from twinlab.loop import run_open_loop
from twinlab.metrics import residuals
from twinlab.rc1 import RC1


def fit_rc1(moments: list[dict], start=(0.02, 3e6, 5.0)) -> RC1:
    """Return an RC1 model with R, C and sun area fitted to these moments."""
    measured = [m["unit1.zone_air_temp"] for m in moments]

    def model_from(x):
        log_R, log_C, area = x
        return RC1(R=math.exp(log_R), C=math.exp(log_C), solar_area_m2=area)

    def all_residuals(x):
        return residuals(measured, run_open_loop(model_from(x), moments))

    R0, C0, A0 = start
    result = least_squares(
        all_residuals,
        x0=[math.log(R0), math.log(C0), A0],
        bounds=([-math.inf, -math.inf, 0.0], [math.inf, math.inf, math.inf]),
    )
    if not result.success:
        raise RuntimeError(f"fit didn't converge: {result.message}")
    return model_from(result.x)
