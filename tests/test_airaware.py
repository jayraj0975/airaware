import math

import numpy as np
import pandas as pd

from airaware.aqi import category, sub_index
from airaware.data import clean_hourly, station_daily
from airaware.model import (AIRAWARE, CAMS, FEATURES, HISTORY, HISTORY_ONLY, OPTIMISTIC, PERSISTENCE, VINTAGE, WX, ChangeModel,
                            category_index, dm_test, explain, features, interval, train, train_rows)


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
    assert category(100.4)[0] == "Satisfactory" and category(100.5)[0] == "Moderate"  # category of the shown number
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
                          "pressure": 1010.0, "blh": 600.0, "cams_pm25": 20.0, "cams_pm10": 30.0})
    a = features(daily).set_index("date")
    changed = daily.copy()
    changed.loc[changed["date"] == "2024-01-16", ["aqi", "pm25", "pm10"]] = [999.0, 999.0, 999.0]
    b = features(changed).set_index("date")
    d = pd.Timestamp("2024-01-15")
    assert a.loc[d, "target"] == 50 + 15 * 5 and b.loc[d, "target"] == 999
    pd.testing.assert_series_equal(a.loc[d, FEATURES], b.loc[d, FEATURES])


def _toy(n=60):
    days = pd.date_range("2024-01-01", periods=n)
    rng = np.random.default_rng(0)
    return pd.DataFrame({"date": days, "city": "Pune", "aqi": 100 + rng.normal(0, 20, n), "pm25": 30.0, "pm10": 60.0,
                         "temp": 25 + rng.normal(0, 2, n), "humidity": 60.0, "rain": 0.0, "wind": 8.0, "wind_u": 1.0,
                         "wind_v": 1.0, "pressure": 1010.0, "blh": 600 + rng.normal(0, 50, n),
                         "cams_pm25": 20 + rng.normal(0, 5, n), "cams_pm10": 30.0})


def test_horizon_features_and_training_cutoff():
    f = features(_toy(), h=3).set_index("date", drop=False)
    d = pd.Timestamp("2024-01-10")
    assert f.loc[d, "target"] == f.loc[d + pd.Timedelta(days=3), "aqi"]
    assert f.loc[d, "temp_next"] == f.loc[d + pd.Timedelta(days=3), "temp"]
    start = pd.Timestamp("2024-02-01")
    tr = train_rows(f.reset_index(drop=True), start, 3)
    assert (tr["date"] + pd.Timedelta(days=3)).max() == start  # every training target was measured by the forecast


def test_explain_adds_up_to_the_forecast():
    f = features(_toy()).dropna(subset=["target"])
    m = ChangeModel().fit(f, f["target"])
    x = f.iloc[[20]]
    total = x["aqi"].iloc[0] + m.model_.named_steps["ridge"].intercept_ + explain(m, x).sum()
    assert abs(total - m.predict(x)[0]) < 1e-9


def test_interval_and_dm_test():
    lo, hi, p = interval(np.array([100.0, 195.0]), np.arange(-10, 11))
    assert lo[0] == 92 and hi[0] == 108 and p[0] == 0 and 0.2 < p[1] < 0.3
    stat, pval = dm_test(np.ones(50), np.ones(50) * 2 + np.sin(np.arange(50)))
    assert stat < 0 and pval < 0.01


def test_insights():
    from airaware.insights import best_hours, cigarettes, diwali_effect, dominant, station_agreement

    assert cigarettes(44) == 2
    assert list(dominant(pd.Series([90.0, 20.0]), pd.Series([100.0, 300.0]))) == ["PM2.5", "PM10"]

    days = pd.date_range("2025-09-01", "2025-11-10")
    daily = pd.DataFrame({"date": days, "city": "Pune", "aqi": 100.0})
    daily.loc[daily["date"] == "2025-10-21", "aqi"] = 250.0  # Diwali 2025
    e = diwali_effect(daily).set_index("offset")
    assert e.loc[0, "change"] == 150 and e.loc[1, "change"] == 0

    t = pd.date_range("2025-01-01", periods=40)
    wave = np.sin(np.arange(40)) * 50 + 150
    st = pd.concat([pd.DataFrame({"city": "Pune", "station": n, "date": t, "aqi": a})
                    for n, a in [("A", wave), ("B", wave + 5), ("C", wave - 5), ("Broken", np.random.default_rng(1).uniform(50, 250, 40))]])
    verdicts = station_agreement(st).set_index("station")["verdict"]
    assert verdicts["A"] == "Agrees with the city" and verdicts["Broken"] == "Out of step with the city"

    profile = pd.DataFrame({"city": "Pune", "month": 1, "hour": range(24), "aqi": [10] * 6 + list(range(100, 118))})
    assert list(best_hours(profile, "Pune", 1)["hour"]) == [6, 7, 8]  # night hours are skipped


# ---------- evaluation rules (forecast vintage, cutoffs, equal test rows) ----------

def _vintage(daily: pd.DataFrame) -> pd.DataFrame:
    """Toy archive of issued forecasts: the realized weather plus an error that grows with the lead."""
    rng = np.random.default_rng(1)
    v = daily[["date", "city"]].copy()
    for w in ["temp", "humidity", "rain", "wind", "wind_u", "wind_v", "pressure"]:
        for k in range(1, 8):
            v[f"{w}_lead{k}"] = daily[w].to_numpy() + rng.normal(0, 0.3 * k, len(daily))
    return v


def test_issued_forecast_columns_come_from_runs_before_the_forecast_day():
    daily = _toy()
    v = _vintage(daily)
    f = features(daily, h=3, vintage=v).set_index("date")
    vv = v.set_index("date")
    d = pd.Timestamp("2024-01-10")
    assert f.loc[d, "fc_today_temp"] == vv.loc[d, "temp_lead1"]  # issued on D - 1
    assert f.loc[d, "fc_target_temp"] == vv.loc[d + pd.Timedelta(days=3), "temp_lead4"]  # issued on (D + 3) - 4 = D - 1


def test_no_feature_depends_on_any_later_aqi():
    daily = _toy()
    v = _vintage(daily)
    d = pd.Timestamp("2024-01-20")
    base = features(daily, h=2, vintage=v).set_index("date")
    later = daily.copy()
    later.loc[later["date"] > d, ["aqi", "pm25", "pm10"]] = 999.0  # every observation after D changes
    moved = features(later, h=2, vintage=v).set_index("date")
    cols = sorted(set(FEATURES + VINTAGE))
    pd.testing.assert_series_equal(base.loc[d, cols], moved.loc[d, cols])
    assert moved.loc[d, "target"] == 999.0  # only the target sees the future


def test_conservative_benchmark_has_no_weather_or_cams():
    weatherish = set(WX + CAMS) | {c for c in FEATURES if c.endswith("_next")}
    assert not weatherish & set(HISTORY) and not any(c.startswith("fc_") for c in HISTORY)
    f = features(_toy()).dropna(subset=["target"])
    m = ChangeModel(cols=tuple(HISTORY)).fit(f, f["target"])
    scrambled = f.assign(**{c: f[c].sample(frac=1, random_state=2).to_numpy() for c in WX + CAMS})
    assert np.allclose(m.predict(f), m.predict(scrambled))


def _two_cities() -> pd.DataFrame:
    days = pd.date_range("2024-06-01", "2026-01-31")
    rng = np.random.default_rng(3)
    out = []
    for city, level in [("Pune", 110), ("Mumbai", 95)]:
        season = 40 * np.cos(2 * np.pi * days.dayofyear / 365.25)
        aqi = level + season + np.cumsum(rng.normal(0, 4, len(days))) * 0.3 + rng.normal(0, 8, len(days))
        out.append(pd.DataFrame({"date": days, "city": city, "aqi": aqi, "pm25": aqi * 0.4, "pm10": aqi * 0.9,
                                 "temp": 26 - season / 10 + rng.normal(0, 1, len(days)), "humidity": 60.0 + rng.normal(0, 5, len(days)),
                                 "rain": 0.0, "wind": 8.0 + rng.normal(0, 1, len(days)), "wind_u": 1.0, "wind_v": 1.0,
                                 "pressure": 1010.0, "blh": 600.0, "cams_pm25": aqi * 0.3, "cams_pm10": aqi * 0.5}))
    d = pd.concat(out, ignore_index=True)
    d.loc[d.sample(frac=0.05, random_state=4).index, "aqi"] = np.nan  # stations miss days
    d.loc[d.sample(frac=0.05, random_state=5).index, ["temp", "cams_pm25"]] = np.nan
    return d


def test_walk_forward_is_reproducible_fair_and_survives_missing_data():
    daily = _two_cities()
    v = _vintage(daily.fillna({"temp": 26.0}))
    v.loc[v.sample(frac=0.05, random_state=6).index, "temp_lead2"] = np.nan  # archived runs have holes too
    a, b = train(daily, v), train(daily, v)
    pd.testing.assert_frame_equal(a.table, b.table)
    pd.testing.assert_frame_equal(a.horizons, b.horizons)
    assert a.table[["MAE", "RMSE"]].notna().all().all()
    # Every method at every horizon was scored on the same number of forecasts (the same test rows).
    assert a.horizons.groupby("Days ahead")["Forecasts"].nunique().eq(1).all()
    assert {AIRAWARE, HISTORY_ONLY, PERSISTENCE, OPTIMISTIC} <= set(a.table["Method"])
    assert a.test["target"].notna().all() and a.test["date"].min() >= pd.Timestamp("2025-10-01")
    # Without an archive of issued forecasts, the served model falls back to station history only.
    c = train(daily, pd.DataFrame())
    assert not c.vintage and set(c.final[1].cols) == set(HISTORY)
