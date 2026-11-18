import pytest

from gateway.units import UnitError, convert


@pytest.mark.parametrize("f, c", [(32, 0.0), (212, 100.0), (-40, -40.0), (70.4, 21.333333)])
def test_fahrenheit_to_celsius(f, c):
    assert convert(f, "DEG_F", "DEG_C") == pytest.approx(c, abs=1e-6)


def test_celsius_to_kelvin_and_back():
    assert convert(21.5, "DEG_C", "K") == pytest.approx(294.65)
    assert convert(294.65, "K", "DEG_C") == pytest.approx(21.5)


def test_watts_to_kilowatts():
    assert convert(2500, "W", "KiloW") == pytest.approx(2.5)


def test_same_unit_is_unchanged():
    assert convert(21.52, "DEG_C", "DEG_C") == 21.52


def test_different_quantities_are_refused():
    with pytest.raises(UnitError, match="can't convert"):
        convert(5, "KiloW", "DEG_C")


def test_unknown_unit_is_refused():
    with pytest.raises(UnitError, match="unknown unit"):
        convert(5, "FURLONG", "DEG_C")
