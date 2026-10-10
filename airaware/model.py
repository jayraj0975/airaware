"""Forecast the AQI 1-7 days ahead from today's air, today's weather and the weather forecast for the target day.

Run `python -m airaware.model` to run the walk-forward evaluation and write reports/metrics.md.
"""

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, RegressorMixin
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from airaware.aqi import CATEGORIES
from airaware.data import load, load_vintage

REPORT = Path(__file__).resolve().parent.parent / "reports" / "metrics.md"
WX = ["temp", "humidity", "rain", "wind", "wind_u", "wind_v", "pressure", "blh"]
CAMS = ["cams_pm25", "cams_pm10"]  # Copernicus CAMS particles: analysis for the past, its forecast at prediction time
DIWALI = pd.to_datetime(["2020-11-14", "2021-11-04", "2022-10-24", "2023-11-12", "2024-11-01", "2025-10-21", "2026-11-08"])

TODAY = ["aqi", "aqi_lag1", "aqi_lag2", "aqi_7d", "pm25", "pm10", *WX, *CAMS, "doy_sin", "doy_cos", "weekday", "diwali", "mumbai"]
FORECAST = [w + "_next" for w in WX + CAMS]
FEATURES = TODAY + FORECAST
# The conservative benchmark: only what the stations measured and the calendar. No weather, no CAMS, so no input can
# be more accurate in this backtest than it would have been on the day.
HISTORY = ["aqi", "aqi_lag1", "aqi_lag2", "aqi_7d", "pm25", "pm10", "doy_sin", "doy_cos", "weekday", "diwali", "mumbai"]
# Weather as actually forecast at the time (Open-Meteo's archive of issued runs; no boundary-layer height, no CAMS).
VWX = ["temp", "humidity", "rain", "wind", "wind_u", "wind_v", "pressure"]
VINTAGE = HISTORY + [f"fc_today_{w}" for w in VWX] + [f"fc_target_{w}" for w in VWX]
MAX_LEAD = 7  # the archive keeps runs up to 7 days old; the target-day forecast needs lead h + 1
# Days ahead. The public archive runs about four days behind, so "tomorrow" is usually five days after the last reading.
HORIZONS = range(1, 8)


def features(daily: pd.DataFrame, h: int = 1, vintage: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row per city and day D: what is known by the evening of D, plus the target AQI of D+h.

    The `_next` columns are the weather on the target day D+h. In this archive they are the REALIZED weather
    (ERA5) and CAMS analysis, which nobody had on day D, so they can only give an optimistic backtest.
    With `vintage`, the `fc_` columns are weather as it was actually forecast: today's from the run issued a day
    before, the target day's from runs issued h + 1 days before it (so issued on D - 1, before the forecast is made).
    Lags use calendar days, so a missing reading stays missing instead of borrowing an older one.
    """
    out = []
    if vintage is not None:
        vintage = vintage.set_index(["city", "date"])
    for city, d in daily.groupby("city"):
        d = d.set_index("date").asfreq("D").assign(city=city)
        f = d[["city", "aqi", "pm25", "pm10", *WX, *CAMS]].copy()
        f["aqi_lag1"], f["aqi_lag2"] = d["aqi"].shift(1), d["aqi"].shift(2)
        f["aqi_7d"] = d["aqi"].rolling(7, min_periods=4).mean()
        for w in WX + CAMS:
            f[w + "_next"] = d[w].shift(-h)
        nxt = f.index + pd.Timedelta(days=h)
        doy = 2 * np.pi * nxt.dayofyear / 365.25
        f["doy_sin"], f["doy_cos"], f["weekday"] = np.sin(doy), np.cos(doy), nxt.weekday
        f["diwali"] = [int(np.abs((DIWALI - t).days).min() <= 3) for t in nxt]
        f["mumbai"] = int(city == "Mumbai")
        f["target"] = d["aqi"].shift(-h)
        if vintage is not None:
            v = vintage.loc[city].reindex(d.index) if city in vintage.index.get_level_values(0) else pd.DataFrame(index=d.index)
            for w in VWX:
                f[f"fc_today_{w}"] = v.get(f"{w}_lead1")
                lead = f"{w}_lead{h + 1}"
                f[f"fc_target_{w}"] = v[lead].shift(-h) if lead in v else np.nan
        out.append(f)
    return pd.concat(out).rename_axis("date").reset_index()


def category_index(aqi: np.ndarray) -> np.ndarray:
    return np.searchsorted([c[0] for c in CATEGORIES[:-1]], np.asarray(aqi), side="left")


def scores(y: np.ndarray, p: np.ndarray) -> dict:
    bad = y > 200  # Poor or worse
    return {
        "MAE": mean_absolute_error(y, p),
        "RMSE": mean_squared_error(y, p) ** 0.5,
        "R2": r2_score(y, p),
        "Category accuracy": float(np.mean(category_index(y) == category_index(p))),
        "Poor-day recall": float(np.mean(p[bad] > 200)) if bad.any() else float("nan"),
    }


def dm_test(loss_a: np.ndarray, loss_b: np.ndarray, lags: int = 7) -> tuple[float, float]:
    """Diebold-Mariano test that two forecasts have equal mean loss; returns (statistic, two-sided p-value).

    Daily errors are autocorrelated, so the variance uses a Newey-West estimate over `lags` days.
    A negative statistic means forecast A has the lower loss.
    """
    d = np.asarray(loss_a, float) - np.asarray(loss_b, float)
    n, dc = len(d), d - d.mean()
    var = dc @ dc / n + 2 * sum((1 - k / (lags + 1)) * (dc[k:] @ dc[:-k]) / n for k in range(1, lags + 1))
    stat = d.mean() / math.sqrt(var / n)
    return stat, math.erfc(abs(stat) / math.sqrt(2))


def p_text(p: float) -> str:
    return "p < 0.001" if p < 0.001 else f"p = {p:.3f}"


def interval(pred: np.ndarray, residuals: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """80% range and chance of a Poor-or-worse day, from past out-of-sample errors (split conformal)."""
    pred, residuals = np.asarray(pred, float), np.asarray(residuals, float)
    lo, hi = np.quantile(residuals, [0.1, 0.9])
    return np.maximum(pred + lo, 0), pred + hi, (pred[:, None] + residuals[None, :] > 200).mean(axis=1)


def ridge():
    return make_pipeline(SimpleImputer(), StandardScaler(), Ridge(alpha=10.0))


def gbm() -> HistGradientBoostingRegressor:
    return HistGradientBoostingRegressor(max_iter=200, learning_rate=0.03, max_depth=3, min_samples_leaf=40,
                                         l2_regularization=3.0, random_state=0)


class ChangeModel(RegressorMixin, BaseEstimator):
    """Learns tomorrow's AQI minus today's, so "no change" is where every forecast starts.

    AQI moves slowly from one day to the next; predicting the level directly lost to plain persistence.
    """

    def __init__(self, make=ridge, cols=tuple(FEATURES), need=()):
        self.make, self.cols, self.need = make, cols, need  # `need`: train only on rows that have these columns

    def fit(self, X, y):
        known = (X["aqi"].notna() & X[list(self.need)].notna().all(axis=1)).to_numpy()
        self.model_ = self.make().fit(X.loc[known, list(self.cols)], (y - X["aqi"])[known])
        return self

    def predict(self, X):
        return self.model_.predict(X[list(self.cols)]) + X["aqi"].to_numpy()


def explain(model: "ChangeModel", x: pd.DataFrame) -> pd.Series:
    """Exact split of one linear forecast: forecast = today's AQI + baseline change + sum of these terms."""
    imputer, scaler, reg = model.model_.named_steps.values()
    z = scaler.transform(imputer.transform(x[list(model.cols)]))[0]
    return pd.Series(reg.coef_ * z, index=list(model.cols))


TEST_FROM = pd.Timestamp("2025-10-01")  # walk-forward months start here; dense station data begins Feb 2025
AIRAWARE = "AirAware: station history + weather forecasts as issued"
HISTORY_ONLY = "Station history only (no weather, no CAMS)"
OPTIMISTIC = "Upper bound: realized weather and CAMS (not available on the day)"
PERSISTENCE = "Persistence (tomorrow = today)"
FC = tuple(c for c in VINTAGE if c.startswith("fc_"))


def served(h: int, vintage: bool = True) -> ChangeModel:
    """The model the site uses for h days ahead: issued weather forecasts where the archive reaches (lead h + 1 <= 7),
    otherwise station history only. Never inputs that were unknown on the day the forecast is made."""
    if vintage and h + 1 <= MAX_LEAD:
        return ChangeModel(cols=tuple(VINTAGE), need=FC)
    return ChangeModel(cols=tuple(HISTORY))


def train_rows(f: pd.DataFrame, start: pd.Timestamp, h: int) -> pd.DataFrame:
    """Rows whose target (the AQI h days later) had been measured by the first forecast of a month starting at `start`."""
    return f[f["date"] + pd.Timedelta(days=h) <= start]


def predict_month(tr: pd.DataFrame, te: pd.DataFrame, h: int, vintage: bool) -> tuple[dict, ChangeModel]:
    """Every method, trained only on `tr`, forecasting exactly the rows of `te` (so all are scored on the same days)."""
    model = served(h, vintage).fit(tr, tr["target"])
    preds = {PERSISTENCE: te["aqi"].to_numpy(),
             HISTORY_ONLY: ChangeModel(cols=tuple(HISTORY)).fit(tr, tr["target"]).predict(te),
             OPTIMISTIC: ChangeModel().fit(tr, tr["target"]).predict(te),
             AIRAWARE: model.predict(te)}
    if h == 1:  # simple baselines and alternative learners, next day only
        month = (te["date"] + pd.Timedelta(days=1)).dt.month
        seasonal = tr.assign(m=(tr["date"] + pd.Timedelta(days=1)).dt.month).groupby(["city", "m"])["target"].mean()
        city_mean = tr.groupby("city")["target"].mean()
        keys = list(zip(te["city"], month))
        preds["7-day average"] = te["aqi_7d"].fillna(te["aqi"]).to_numpy()
        preds["Seasonal average (city, month)"] = seasonal.reindex(keys).to_numpy(dtype=float, copy=True)
        missing = np.isnan(preds["Seasonal average (city, month)"])
        preds["Seasonal average (city, month)"][missing] = te["city"].map(city_mean).to_numpy()[missing]
        cols = list(model.cols)
        rows = tr.dropna(subset=list(model.need)) if model.need else tr
        preds["Linear regression on the AQI level"] = ridge().fit(rows[cols], rows["target"]).predict(te[cols])
        preds["Gradient boosting on the change"] = ChangeModel(gbm, cols=model.cols, need=model.need).fit(tr, tr["target"]).predict(te)
    return preds, model


@dataclass
class Result:
    models: dict  # month start -> next-day AirAware model trained on everything before that month
    table: pd.DataFrame  # next-day metrics per method and city over all walk-forward months
    importance: pd.Series
    test: pd.DataFrame  # next-day test rows with the AirAware forecast, its 80% range and chance of a Poor day
    horizons: pd.DataFrame  # MAE, 80%-range coverage and forecast count per days-ahead and method
    dm: tuple  # Diebold-Mariano (statistic, p), next-day AirAware against persistence, absolute error
    final: dict  # days ahead -> AirAware trained on every row, for live forecasts
    residuals: dict  # days ahead -> all walk-forward errors, for live ranges
    dm_history: tuple = (float("nan"), float("nan"))  # same test, station-history-only model against persistence
    vintage: bool = True  # whether archived issued forecasts were available (else AirAware = station history only)

    def model_for(self, day: pd.Timestamp) -> ChangeModel:
        return self.models[day.to_period("M").start_time]


def dm_by_date(test: pd.DataFrame, a: str, b: str) -> tuple[float, float]:
    """Diebold-Mariano on the daily mean absolute error across cities, so the Newey-West lags run along time and
    never across the boundary between two cities' series."""
    g = test.assign(la=(test["target"] - test[a]).abs(), lb=(test["target"] - test[b]).abs()).groupby("date")[["la", "lb"]].mean()
    return dm_test(g["la"].to_numpy(), g["lb"].to_numpy())


def train(daily: pd.DataFrame | None = None, vintage: pd.DataFrame | None = None) -> Result:
    """Walk-forward test: at the start of each month, retrain on everything whose target was already measured,
    then forecast that month. Every method is scored on the same test rows at every horizon.

    The 80% range for a month comes from the errors of earlier walk-forward months only (in-sample errors until
    there are 60 of them), so its coverage on the test months is an honest check.
    """
    daily = load() if daily is None else daily
    vintage = load_vintage() if vintage is None else vintage
    has_vintage = vintage is not None and not vintage.empty
    models, imps, rows, horizon_rows, final, residuals = {}, [], [], [], {}, {}
    for h in HORIZONS:
        f = features(daily, h, vintage if has_vintage else None).dropna(subset=["target"])
        f = f[f["aqi"].notna() | (f["date"] < TEST_FROM)]  # test days need today's AQI; every method gets the same days
        parts, errors = [], []
        for m in pd.period_range(TEST_FROM, f["date"].max(), freq="M"):
            tr = train_rows(f, m.start_time, h)
            te = f[(f["date"] >= m.start_time) & (f["date"] <= m.end_time)].copy()
            if te.empty:
                continue
            preds, model = predict_month(tr, te, h, has_vintage)
            if h == 1:
                models[m.start_time] = model
                cols = list(model.cols)
                imp = permutation_importance(model, te[cols], te["target"], scoring="neg_mean_absolute_error", n_repeats=5, random_state=0)
                imps.append(pd.Series(imp.importances_mean * len(te), index=cols))
            known = model_rows(tr, model)
            past = errors if len(errors) >= 60 else list(known["target"] - model.predict(known))
            for name, p in preds.items():
                te[name] = p
            te["lo"], te["hi"], te["p_poor"] = interval(te[AIRAWARE], past)
            errors += list(te["target"] - te[AIRAWARE])
            parts.append(te)
        te = pd.concat(parts)
        final[h], residuals[h] = served(h, has_vintage).fit(f, f["target"]), np.array(errors)
        for name in (AIRAWARE, HISTORY_ONLY, PERSISTENCE, OPTIMISTIC):
            stat, p = dm_by_date(te, name, PERSISTENCE) if name != PERSISTENCE else (np.nan, np.nan)
            horizon_rows.append({"Days ahead": h, "Method": name, "MAE": mean_absolute_error(te["target"], te[name]),
                                 "Forecasts": len(te), "80% range coverage": float(te["target"].between(te["lo"], te["hi"]).mean()),
                                 "DM p vs persistence": p})
        if h == 1:
            test = te
            for name in preds:
                for city, part in [("Both", te), ("Pune", te[te["city"] == "Pune"]), ("Mumbai", te[te["city"] == "Mumbai"])]:
                    rows.append({"Method": name, "City": city, **scores(part["target"].to_numpy(), part[name].to_numpy())})

    test = test.sort_values(["city", "date"])
    dm, dm_history = dm_by_date(test, AIRAWARE, PERSISTENCE), dm_by_date(test, HISTORY_ONLY, PERSISTENCE)
    importance = (sum(i.fillna(0) for i in imps) / len(test)).sort_values(ascending=False)
    test = test.rename(columns={AIRAWARE: "predicted", PERSISTENCE: "persistence"})
    horizons = pd.DataFrame(horizon_rows)
    horizons.loc[horizons["Method"] != AIRAWARE, "80% range coverage"] = np.nan  # ranges belong to the served model
    return Result(models, pd.DataFrame(rows), importance, test, horizons, dm, final, residuals, dm_history, has_vintage)


def model_rows(f: pd.DataFrame, model: ChangeModel) -> pd.DataFrame:
    """The rows a ChangeModel trains on: today's AQI known, plus whatever columns it needs."""
    return f[f["aqi"].notna() & f[list(model.need)].notna().all(axis=1)]


def as_vintage(daily: pd.DataFrame) -> pd.DataFrame:
    """For live forecasts: the best weather known now (ERA5 for past days, the current forecast ahead) in the archive's
    column layout. Nothing here is from the future; it is only fresher than the archived runs the model trained on."""
    v = daily[["date", "city"]].copy()
    for w in VWX:
        for k in range(1, MAX_LEAD + 2):
            v[f"{w}_lead{k}"] = daily[w]
    return v


def forecast_now(daily: pd.DataFrame, r: Result) -> pd.DataFrame:
    """Forecasts from each city's latest measured day, as far ahead as the weather forecast reaches."""
    out = []
    live_wx = as_vintage(daily)
    for h in HORIZONS:
        f = features(daily, h, live_wx)
        model = r.final[h]
        need = [c for c in model.cols if c.startswith("fc_target_")]
        latest = f.loc[f[f["aqi"].notna()].groupby("city")["date"].idxmax()].dropna(subset=need)
        if latest.empty:
            continue
        pred = model.predict(latest)
        lo, hi, p_poor = interval(pred, r.residuals[h])
        out.append(pd.DataFrame({"city": latest["city"].to_numpy(), "made_from": latest["date"].to_numpy(),
                                 "date": (latest["date"] + pd.Timedelta(days=h)).to_numpy(), "days_ahead": h,
                                 "forecast": pred, "lo": lo, "hi": hi, "p_poor": p_poor}))
    return pd.concat(out).sort_values(["city", "date"]).reset_index(drop=True)


def write_report(r: Result) -> str:
    both = r.table[r.table["City"] == "Both"].drop(columns="City").set_index("Method")
    per_city = r.table.pivot(index="Method", columns="City", values="MAE")[["Pune", "Mumbai"]]
    t = r.test
    hz = r.horizons.pivot(index="Days ahead", columns="Method", values="MAE")[[AIRAWARE, HISTORY_ONLY, PERSISTENCE, OPTIMISTIC]]
    cov = r.horizons[r.horizons["Method"] == AIRAWARE].set_index("Days ahead")[["80% range coverage", "DM p vs persistence", "Forecasts"]]
    served_text = ("station history plus weather forecasts **as they were issued** (Open-Meteo's archive of past runs; "
                   "today's weather from the run issued a day earlier, the target day's from runs issued h + 1 days "
                   "before it), and station history only at 7 days ahead, where no archived run is old enough"
                   if r.vintage else "station history only (the archive of issued forecasts was not available)")
    md = (
        f"# AirAware results\n\nGenerated by `python -m airaware.model`. Walk-forward test: at the start of each month from "
        f"{TEST_FROM:%B %Y}, every method is retrained on the rows whose target had already been measured, then forecasts "
        f"that month. Next day: {len(t)} city-day forecasts for {t['date'].min() + pd.Timedelta(days=1):%d %b %Y} to "
        f"{t['date'].max() + pd.Timedelta(days=1):%d %b %Y}; every method is scored on exactly the same rows. Lower MAE/RMSE is better.\n\n"
        f"**AirAware** (the model the site serves) uses {served_text}. "
        f"**Station history only** uses the stations' AQI, PM2.5 and PM10 (today, the two days before, the 7-day mean), "
        f"the calendar and the city: no weather and no CAMS at all, so it is the most conservative benchmark. "
        f"**Upper bound** adds the realized (ERA5) weather and the CAMS analysis for the target day. Nobody has those on "
        f"the day, and CAMS keeps no archive of its past forecasts, so this row only shows how much better the forecast "
        f"could be with perfect weather and particle forecasts. It is not an estimate of live accuracy.\n\n"
        f"## Next day, both cities\n\n{both.round(3).to_markdown()}\n\n## Next-day MAE by city\n\n{per_city.round(1).to_markdown()}\n\n"
        f"Diebold-Mariano tests against persistence (absolute error, averaged over the two cities per day, Newey-West 7 lags): "
        f"AirAware statistic {r.dm[0]:.2f}, {p_text(r.dm[1])}; station history only statistic {r.dm_history[0]:.2f}, {p_text(r.dm_history[1])}.\n\n"
        f"## Further ahead (MAE)\n\n{hz.round(2).to_markdown()}\n\n"
        f"## AirAware's 80% ranges and significance against persistence, by horizon\n\n{cov.round(3).to_markdown()}\n\n"
        f"## What the next-day model relies on (permutation importance, MAE increase)\n\n{r.importance.head(12).round(2).rename('MAE increase').to_markdown()}\n"
    )
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text(md)
    return md


if __name__ == "__main__":
    print(write_report(train()))
