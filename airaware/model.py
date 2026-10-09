"""Forecast tomorrow's AQI from today's air, today's weather and tomorrow's weather forecast.

Run `python -m airaware.model` to train, compare against baselines on the most recent year, and write
reports/metrics.md.
"""

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
DIWALI = pd.to_datetime(["2020-11-14", "2021-11-04", "2022-10-24", "2023-11-12", "2024-11-01", "2025-10-21", "2026-11-08"])

TODAY = ["aqi", "aqi_lag1", "aqi_lag2", "aqi_7d", "pm25", "pm10", *WX, "doy_sin", "doy_cos", "weekday", "diwali", "mumbai"]
FORECAST = [w + "_next" for w in WX]
FEATURES = TODAY + FORECAST


def features(daily: pd.DataFrame) -> pd.DataFrame:
    """One row per city and day D: what is known by the evening of D, plus the target AQI of D+1.

    Lags use calendar days, so a missing reading stays missing instead of borrowing an older one.
    """
    out = []
    for city, d in daily.groupby("city"):
        d = d.set_index("date").asfreq("D").assign(city=city)
        f = d[["city", "aqi", "pm25", "pm10", *WX]].copy()
        f["aqi_lag1"], f["aqi_lag2"] = d["aqi"].shift(1), d["aqi"].shift(2)
        f["aqi_7d"] = d["aqi"].rolling(7, min_periods=4).mean()
        for w in WX:
            f[w + "_next"] = d[w].shift(-1)  # tomorrow's weather: the forecast at prediction time
        nxt = f.index + pd.Timedelta(days=1)
        doy = 2 * np.pi * nxt.dayofyear / 365.25
        f["doy_sin"], f["doy_cos"], f["weekday"] = np.sin(doy), np.cos(doy), nxt.weekday
        f["diwali"] = [int(np.abs((DIWALI - t).days).min() <= 3) for t in nxt]
        f["mumbai"] = int(city == "Mumbai")
        f["target"] = d["aqi"].shift(-1)
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


TEST_FROM = pd.Timestamp("2025-10-01")  # walk-forward months start here; dense station data begins Feb 2025
AIRAWARE = "AirAware: linear regression on the change"


def predict_month(tr: pd.DataFrame, te: pd.DataFrame) -> tuple[dict, ChangeModel]:
    """Every method, trained only on `tr`, forecasting the rows of `te`."""
    month = lambda df: (df["date"] + pd.Timedelta(days=1)).dt.month
    seasonal = tr.assign(m=month(tr)).groupby(["city", "m"])["target"].mean()
    city_mean = tr.groupby("city")["target"].mean()
    preds = {
        "Persistence (tomorrow = today)": te["aqi"].to_numpy(),
        "7-day average": te["aqi_7d"].fillna(te["aqi"]).to_numpy(),
        "Seasonal average (city, month)": seasonal.reindex(list(zip(te["city"], month(te)))).fillna(
            te["city"].map(city_mean).set_axis(list(zip(te["city"], month(te))))).to_numpy(),
    }
    preds["Linear regression on the AQI level"] = ridge().fit(tr[FEATURES], tr["target"]).predict(te[FEATURES])
    preds["Gradient boosting on the change"] = ChangeModel(gbm).fit(tr, tr["target"]).predict(te)
    preds["AirAware without tomorrow's weather"] = ChangeModel(cols=tuple(TODAY)).fit(tr, tr["target"]).predict(te)
    model = ChangeModel().fit(tr, tr["target"])
    preds[AIRAWARE] = model.predict(te)
    return preds, model


@dataclass
class Result:
    models: dict  # month start -> AirAware model trained on everything before that month
    table: pd.DataFrame  # metrics per method and city over all walk-forward months
    importance: pd.Series
    test: pd.DataFrame  # test rows with the AirAware forecast and the month it belongs to

    def model_for(self, day: pd.Timestamp) -> ChangeModel:
        return self.models[day.to_period("M").start_time]


def train(daily: pd.DataFrame | None = None) -> Result:
    """Walk-forward test: at the start of each month, retrain on everything before it and forecast that month.

    A row dated D is in the training set of month M only if D is before M, so its target (the AQI of D+1)
    was known by the first forecast of M.
    """
    f = features(load() if daily is None else daily).dropna(subset=["target"])
    f = f[f["aqi"].notna() | (f["date"] < TEST_FROM)]  # test days need today's AQI; every method gets the same days
    models, parts, imps = {}, [], []
    for m in pd.period_range(TEST_FROM, f["date"].max(), freq="M"):
        tr = f[f["date"] < m.start_time]
        te = f[(f["date"] >= m.start_time) & (f["date"] <= m.end_time)].copy()
        if te.empty:
            continue
        preds, model = predict_month(tr, te)
        models[m.start_time] = model
        for name, p in preds.items():
            te[name] = p
        parts.append(te)
        imp = permutation_importance(model, te[FEATURES], te["target"], scoring="neg_mean_absolute_error", n_repeats=5, random_state=0)
        imps.append(pd.Series(imp.importances_mean * len(te), index=FEATURES))
    te = pd.concat(parts)

    rows = []
    for name in preds:
        for city, part in [("Both", te), ("Pune", te[te["city"] == "Pune"]), ("Mumbai", te[te["city"] == "Mumbai"])]:
            rows.append({"Method": name, "City": city, **scores(part["target"].to_numpy(), part[name].to_numpy())})
    importance = (sum(imps) / len(te)).sort_values(ascending=False)
    te = te.rename(columns={AIRAWARE: "predicted", "Persistence (tomorrow = today)": "persistence"})
    return Result(models, pd.DataFrame(rows), importance, te)


def write_report(r: Result) -> str:
    both = r.table[r.table["City"] == "Both"].drop(columns="City").set_index("Method")
    per_city = r.table.pivot(index="Method", columns="City", values="MAE")[["Pune", "Mumbai"]]
    md = (
        f"# AirAware results\n\nWalk-forward test: at the start of each month from {TEST_FROM:%B %Y}, every method is retrained on "
        f"everything before that month and forecasts it. {len(r.test)} city-day forecasts, up to "
        f"{r.test['date'].max() + pd.Timedelta(days=1):%d %b %Y}. Lower MAE/RMSE is better.\n\n"
        f"## Both cities\n\n{both.round(3).to_markdown()}\n\n## MAE by city\n\n{per_city.round(1).to_markdown()}\n\n"
        f"## What the model relies on (permutation importance, MAE increase)\n\n{r.importance.head(12).round(2).rename("MAE increase").to_markdown()}\n"
    )
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text(md)
    return md


if __name__ == "__main__":
    print(write_report(train()))
