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
from airaware.data import load

REPORT = Path(__file__).resolve().parent.parent / "reports" / "metrics.md"
WX = ["temp", "humidity", "rain", "wind", "wind_u", "wind_v", "pressure", "blh"]
CAMS = ["cams_pm25", "cams_pm10"]  # Copernicus CAMS particles: analysis for the past, its forecast at prediction time
DIWALI = pd.to_datetime(["2020-11-14", "2021-11-04", "2022-10-24", "2023-11-12", "2024-11-01", "2025-10-21", "2026-11-08"])

TODAY = ["aqi", "aqi_lag1", "aqi_lag2", "aqi_7d", "pm25", "pm10", *WX, *CAMS, "doy_sin", "doy_cos", "weekday", "diwali", "mumbai"]
FORECAST = [w + "_next" for w in WX + CAMS]
FEATURES = TODAY + FORECAST
# Days ahead. The public archive runs about four days behind, so "tomorrow" is usually five days after the last reading.
HORIZONS = range(1, 8)


def features(daily: pd.DataFrame, h: int = 1) -> pd.DataFrame:
    """One row per city and day D: what is known by the evening of D, plus the target AQI of D+h.

    The `_next` columns are the weather on the target day D+h (a weather forecast at prediction time).
    Lags use calendar days, so a missing reading stays missing instead of borrowing an older one.
    """
    out = []
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

    def __init__(self, make=ridge, cols=tuple(FEATURES)):
        self.make, self.cols = make, cols

    def fit(self, X, y):
        known = X["aqi"].notna().to_numpy()
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
AIRAWARE = "AirAware: linear regression on the change"
PERSISTENCE = "Persistence (tomorrow = today)"


def train_rows(f: pd.DataFrame, start: pd.Timestamp, h: int) -> pd.DataFrame:
    """Rows whose target (the AQI h days later) had been measured by the first forecast of a month starting at `start`."""
    return f[f["date"] + pd.Timedelta(days=h) <= start]


def predict_month(tr: pd.DataFrame, te: pd.DataFrame) -> tuple[dict, ChangeModel]:
    """Every method, trained only on `tr`, forecasting the rows of `te`."""
    month = lambda df: (df["date"] + pd.Timedelta(days=1)).dt.month
    seasonal = tr.assign(m=month(tr)).groupby(["city", "m"])["target"].mean()
    city_mean = tr.groupby("city")["target"].mean()
    preds = {
        PERSISTENCE: te["aqi"].to_numpy(),
        "7-day average": te["aqi_7d"].fillna(te["aqi"]).to_numpy(),
        "Seasonal average (city, month)": seasonal.reindex(list(zip(te["city"], month(te)))).fillna(
            te["city"].map(city_mean).set_axis(list(zip(te["city"], month(te))))).to_numpy(),
    }
    preds["Linear regression on the AQI level"] = ridge().fit(tr[FEATURES], tr["target"]).predict(te[FEATURES])
    preds["Gradient boosting on the change"] = ChangeModel(gbm).fit(tr, tr["target"]).predict(te)
    preds["AirAware without tomorrow's forecasts"] = ChangeModel(cols=tuple(TODAY)).fit(tr, tr["target"]).predict(te)
    preds["AirAware without CAMS"] = ChangeModel(cols=tuple(c for c in FEATURES if not c.startswith("cams"))).fit(tr, tr["target"]).predict(te)
    model = ChangeModel().fit(tr, tr["target"])
    preds[AIRAWARE] = model.predict(te)
    return preds, model


@dataclass
class Result:
    models: dict  # month start -> next-day AirAware model trained on everything before that month
    table: pd.DataFrame  # next-day metrics per method and city over all walk-forward months
    importance: pd.Series
    test: pd.DataFrame  # next-day test rows with the AirAware forecast, its 80% range and chance of a Poor day
    horizons: pd.DataFrame  # MAE, 80%-range coverage and forecast count per days-ahead, AirAware and persistence
    dm: tuple  # Diebold-Mariano (statistic, p) for next-day AirAware against persistence, absolute error
    final: dict  # days ahead -> AirAware trained on every row, for live forecasts
    residuals: dict  # days ahead -> all walk-forward errors, for live ranges

    def model_for(self, day: pd.Timestamp) -> ChangeModel:
        return self.models[day.to_period("M").start_time]


def train(daily: pd.DataFrame | None = None) -> Result:
    """Walk-forward test: at the start of each month, retrain on everything whose target was already measured,
    then forecast that month. Next day gets every method; 2-7 days ahead compare AirAware with persistence.

    The 80% range for a month comes from the errors of earlier walk-forward months only (in-sample errors until
    there are 60 of them), so its coverage on the test months is an honest check.
    """
    daily = load() if daily is None else daily
    models, imps, rows, horizon_rows, final, residuals = {}, [], [], [], {}, {}
    for h in HORIZONS:
        f = features(daily, h).dropna(subset=["target"])
        f = f[f["aqi"].notna() | (f["date"] < TEST_FROM)]  # test days need today's AQI; every method gets the same days
        parts, errors = [], []
        for m in pd.period_range(TEST_FROM, f["date"].max(), freq="M"):
            tr = train_rows(f, m.start_time, h)
            te = f[(f["date"] >= m.start_time) & (f["date"] <= m.end_time)].copy()
            if te.empty:
                continue
            if h == 1:
                preds, model = predict_month(tr, te)
                models[m.start_time] = model
                imp = permutation_importance(model, te[FEATURES], te["target"], scoring="neg_mean_absolute_error", n_repeats=5, random_state=0)
                imps.append(pd.Series(imp.importances_mean * len(te), index=FEATURES))
            else:
                model = ChangeModel().fit(tr, tr["target"])
                preds = {PERSISTENCE: te["aqi"].to_numpy(), AIRAWARE: model.predict(te)}
            known = tr[tr["aqi"].notna()]
            past = errors if len(errors) >= 60 else list(known["target"] - model.predict(known))
            for name, p in preds.items():
                te[name] = p
            te["lo"], te["hi"], te["p_poor"] = interval(te[AIRAWARE], past)
            errors += list(te["target"] - te[AIRAWARE])
            parts.append(te)
        te = pd.concat(parts)
        final[h], residuals[h] = ChangeModel().fit(f, f["target"]), np.array(errors)
        for name in (AIRAWARE, PERSISTENCE):
            horizon_rows.append({"Days ahead": h, "Method": name, "MAE": mean_absolute_error(te["target"], te[name]),
                                 "Forecasts": len(te), "80% range coverage": float(te["target"].between(te["lo"], te["hi"]).mean())})
        if h == 1:
            test = te
            for name in preds:
                for city, part in [("Both", te), ("Pune", te[te["city"] == "Pune"]), ("Mumbai", te[te["city"] == "Mumbai"])]:
                    rows.append({"Method": name, "City": city, **scores(part["target"].to_numpy(), part[name].to_numpy())})

    test = test.sort_values(["city", "date"])
    dm = dm_test((test["target"] - test[AIRAWARE]).abs(), (test["target"] - test[PERSISTENCE]).abs())
    importance = (sum(imps) / len(test)).sort_values(ascending=False)
    test = test.rename(columns={AIRAWARE: "predicted", PERSISTENCE: "persistence"})
    horizons = pd.DataFrame(horizon_rows)
    horizons.loc[horizons["Method"] == PERSISTENCE, "80% range coverage"] = np.nan
    return Result(models, pd.DataFrame(rows), importance, test, horizons, dm, final, residuals)


def forecast_now(daily: pd.DataFrame, r: Result) -> pd.DataFrame:
    """Forecasts from each city's latest measured day, as far ahead as the weather forecast reaches."""
    out = []
    for h in HORIZONS:
        f = features(daily, h)
        latest = f.loc[f[f["aqi"].notna()].groupby("city")["date"].idxmax()].dropna(subset=FORECAST)
        if latest.empty:
            continue
        pred = r.final[h].predict(latest)
        lo, hi, p_poor = interval(pred, r.residuals[h])
        out.append(pd.DataFrame({"city": latest["city"].to_numpy(), "made_from": latest["date"].to_numpy(),
                                 "date": (latest["date"] + pd.Timedelta(days=h)).to_numpy(), "days_ahead": h,
                                 "forecast": pred, "lo": lo, "hi": hi, "p_poor": p_poor}))
    return pd.concat(out).sort_values(["city", "date"]).reset_index(drop=True)


def write_report(r: Result) -> str:
    both = r.table[r.table["City"] == "Both"].drop(columns="City").set_index("Method")
    per_city = r.table.pivot(index="Method", columns="City", values="MAE")[["Pune", "Mumbai"]]
    md = (
        f"# AirAware results\n\nWalk-forward test: at the start of each month from {TEST_FROM:%B %Y}, every method is retrained on "
        f"everything before that month and forecasts it. {len(r.test)} city-day forecasts, up to "
        f"{r.test['date'].max() + pd.Timedelta(days=1):%d %b %Y}. Lower MAE/RMSE is better.\n\n"
        f"## Both cities\n\n{both.round(3).to_markdown()}\n\n## MAE by city\n\n{per_city.round(1).to_markdown()}\n\n"
        f"Diebold-Mariano test, AirAware against persistence (absolute error, Newey-West 7 lags): "
        f"statistic {r.dm[0]:.2f}, {p_text(r.dm[1])}.\n\n"
        f"## Further ahead\n\n{r.horizons.pivot(index='Days ahead', columns='Method', values=['MAE', '80% range coverage']).dropna(axis=1, how='all').round(3).to_markdown()}\n\n"
        f"## What the model relies on (permutation importance, MAE increase)\n\n{r.importance.head(12).round(2).rename("MAE increase").to_markdown()}\n"
    )
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text(md)
    return md


if __name__ == "__main__":
    print(write_report(train()))
