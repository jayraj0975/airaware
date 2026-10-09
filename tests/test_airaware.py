import math

import numpy as np
import pandas as pd

from airaware.aqi import category, sub_index
from airaware.data import clean_hourly, station_daily
from airaware.model import FEATURES, category_index, features


def test_sub_index_matches_cpcb_breakpoints():
    assert sub_index("pm2_5", 0) == 0
    assert sub_index("pm2_5", 30) == 50
    assert sub_index("pm2_5", 45) == 75
    assert sub_index("pm2_5", 60) == 100
    assert sub_index("pm10", 250) == 200
    assert sub_index("pm10", 5000) == 500
    assert math.isnan(sub_index("pm10", float("nan")))


def test_categories():
    assert category(50)[0] == "Good"
    assert category(51)[0] == "Satisfactory"
    assert category(150)[0] == "Moderate"
    assert category(450)[0] == "Severe"
    assert list(category_index(np.array([10, 75, 150, 250, 350, 450]))) == [0, 1, 2, 3, 4, 5]


def test_cleaning_drops_error_codes_stuck_sensors_and_impossible_pairs():
    t = pd.date_range("2024-01-01", periods=12, freq="15min").strftime("%Y-%m-%dT%H:%M:%S+05:30")
    raw = pd.DataFrame({
        "datetime": list(t) * 2,
        "parameter": ["pm25"] * 12 + ["pm10"] * 12,
        "value": [985] + [20] * 9 + [70, 30] + [50, 60, 70, 80, 90, 100, 110, 120, 130, 140, 60, 80],
    })
    h = clean_hourly(raw)
    # Hour 0: 985 dropped; the nine 20s are a stuck sensor; hour 2 has PM2.5 70 > PM10 60 at 02:30.
    assert math.isnan(h["pm25"].iloc[0]) and math.isnan(h["pm25"].iloc[1])
    assert h["pm25"].iloc[2] == 30 and h["pm10"].iloc[2] == (130 + 140 + 80) / 3


def test_daily_needs_sixteen_hours():
    hours = pd.date_range("2024-01-01", periods=48, freq="h")
    h = pd.DataFrame({"pm25": 45.0, "pm10": 60.0}, index=hours)  # sub-indices 75 and 60
    h.iloc[24:33] = np.nan  # day two keeps only 15 hours
    d = station_daily(h)
    assert d["aqi"].iloc[0] == 75 and math.isnan(d["aqi"].iloc[1])


def test_features_use_nothing_from_the_target_day():
    days = pd.date_range("2024-01-01", periods=30)
    daily = pd.DataFrame({"date": days, "city": "Pune", "aqi": np.arange(30.0) * 5 + 50, "pm25": 30.0, "pm10": 60.0,
                          "temp": 25.0, "humidity": 60.0, "rain": 0.0, "wind": 8.0, "wind_u": 1.0, "wind_v": 1.0,
                          "pressure": 1010.0, "blh": 600.0})
    a = features(daily).set_index("date")
    changed = daily.copy()
    changed.loc[changed["date"] == "2024-01-16", ["aqi", "pm25", "pm10"]] = [999.0, 999.0, 999.0]
    b = features(changed).set_index("date")
    d = pd.Timestamp("2024-01-15")
    assert a.loc[d, "target"] == 50 + 15 * 5 and b.loc[d, "target"] == 999
    pd.testing.assert_series_equal(a.loc[d, FEATURES], b.loc[d, FEATURES])
