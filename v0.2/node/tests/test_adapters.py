import csv
import time

import pytest

from dtnode.adapters import make


def test_simulated_cools_towards_its_end_value():
    a = make({"id": "tc08", "type": "simulated", "unit": "DEG_C",
              "metrics": {"ch1": {"start": 30, "end": 5, "tau_s": 0.05}}})
    a.connect()
    first = a.read()[0]
    time.sleep(0.3)
    later = a.read()[0]
    assert (first.point_id, first.unit) == ("tc08.ch1", "DEG_C")
    assert first.value > 25 and later.value < 6


def test_unknown_type_is_refused():
    with pytest.raises(ValueError, match="unknown type"):
        make({"id": "x", "type": "nope"})


def write_wide(path, rows):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time", "t_s", "Max (degC) [lepton.max]", "Humidity (%RH) [ambient.humidity]"])
        w.writerows(rows)


def test_csv_replay_plays_rows_as_their_time_comes(tmp_path):
    write_wide(tmp_path / "run.csv", [["2026-11-08T23:18:14+00:00", 0, 29.8, 55.0],
                                      ["2026-11-08T23:18:15+00:00", 1, 29.7, ""]])
    a = make({"id": "replay", "type": "csv", "files": [str(tmp_path / "run.csv")], "speed": 10, "loop": False})
    a.connect()
    first = a.read()
    assert {(r.point_id, r.value, r.unit) for r in first} == {("lepton.max", 29.8, "DEG_C"), ("ambient.humidity", 55.0, "PERCENT_RH")}
    time.sleep(0.15)                                       # 1.5 s of the run at 10x speed
    assert [(r.point_id, r.value) for r in a.read()] == [("lepton.max", 29.7)]   # blank cell = no reading
    assert a.read() == []                                  # end of run, loop = false
