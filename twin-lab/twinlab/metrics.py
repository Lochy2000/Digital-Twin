"""Comparing the twin with the measurements.

residual  = measured - predicted, one per moment. The twin's main output.
            Positive: the room is warmer than the twin expected.
MAE       = mean absolute error: the average size of the residual, ignoring
            its sign. "On average the twin is X °C out."
RMSE      = root mean square error: like MAE, but big misses count extra.
            (Squares each residual, averages, then takes the square root.)
Both are standard in model checking; RR 1 §7 asks for errors in absolute
temperature units, which these are.
"""

import math


def residuals(measured: list[float], predicted: list[float]) -> list[float]:
    if len(measured) != len(predicted):
        raise ValueError("need one prediction per measurement")
    return [m - p for m, p in zip(measured, predicted)]


def mae(res: list[float]) -> float:
    return sum(abs(r) for r in res) / len(res)


def rmse(res: list[float]) -> float:
    return math.sqrt(sum(r * r for r in res) / len(res))
