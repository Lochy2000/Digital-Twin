"""Checks the residual and error measures with numbers easy to work out by hand."""

import math

import pytest

from twinlab.metrics import mae, residuals, rmse


def test_residual_is_measured_minus_predicted():
    assert residuals([20.0, 21.0], [19.5, 22.0]) == [0.5, -1.0]


def test_mae_and_rmse():
    res = [1.0, -1.0, 3.0, -3.0]
    assert mae(res) == 2.0                              # (1+1+3+3) / 4
    assert rmse(res) == pytest.approx(math.sqrt(5.0))   # sqrt((1+1+9+9) / 4)


def test_lengths_must_match():
    with pytest.raises(ValueError):
        residuals([1.0, 2.0], [1.0])
