"""Checks that a long canonical CSV is turned into one dict per moment, in time order."""

from twinlab.data import load_timesteps

CSV = """v,site,point,value,unit,sensor_time,ingest_time,time_source,source,quality
2,site1,unit1.zone_air_temp,15.5,DEG_C,2026-01-15T00:30:00.000Z,x,device,boptest,GOOD
2,site1,weather1.outside_air_temp,-6.0,DEG_C,2026-01-15T00:30:00.000Z,x,device,boptest,GOOD
2,site1,unit1.zone_air_temp,15.0,DEG_C,2026-01-15T00:15:00.000Z,x,device,boptest,GOOD
2,site1,weather1.outside_air_temp,-6.1,DEG_C,2026-01-15T00:15:00.000Z,x,device,boptest,GOOD
"""


def test_rows_become_one_moment_per_time_oldest_first(tmp_path):
    path = tmp_path / "plant.csv"
    path.write_text(CSV)
    moments = load_timesteps(path)

    assert len(moments) == 2                        # 4 rows, 2 moments
    first, second = moments
    assert first["time"] < second["time"]           # sorted, even though the file wasn't
    assert first["unit1.zone_air_temp"] == 15.0
    assert first["weather1.outside_air_temp"] == -6.1
    assert second["unit1.zone_air_temp"] == 15.5
