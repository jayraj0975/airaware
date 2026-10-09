"""Analyses behind the Insights tab: what drives the AQI, the Diwali effect, station agreement, and PM2.5 as cigarettes."""

import numpy as np
import pandas as pd

from airaware.aqi import sub_index
from airaware.model import DIWALI

# Berkeley Earth's rule of thumb: breathing 22 µg/m³ of PM2.5 for a day does about as much harm as one cigarette.
CIGARETTE_PM25 = 22.0


def cigarettes(pm25: float) -> float:
    return pm25 / CIGARETTE_PM25


def dominant(pm25: pd.Series, pm10: pd.Series) -> pd.Series:
    """Which particle sets the AQI: the one with the larger CPCB sub-index."""
    p25, p10 = pm25.map(lambda c: sub_index("pm2_5", c)), pm10.map(lambda c: sub_index("pm10", c))
    return pd.Series(np.where(p25 >= p10, "PM2.5", "PM10"), index=pm25.index).where(p25.notna() & p10.notna())


def diwali_effect(daily: pd.DataFrame, window: int = 10) -> pd.DataFrame:
    """AQI on each day around Diwali, minus the average of days 30 to 11 before it (needs 7 such days).

    One row per city, Diwali year and day offset; average over years to see the festival's typical bump.
    """
    rows = []
    for city, d in daily.dropna(subset=["aqi"]).groupby("city"):
        s = d.set_index("date")["aqi"]
        for day in DIWALI:
            base = s[day - pd.Timedelta(days=30):day - pd.Timedelta(days=11)]
            if len(base) < 7:
                continue
            for k in range(-window, window + 1):
                t = day + pd.Timedelta(days=k)
                if t in s.index:
                    rows.append({"city": city, "year": day.year, "offset": k, "aqi": s[t], "change": s[t] - base.mean()})
    return pd.DataFrame(rows, columns=["city", "year", "offset", "aqi", "change"])


def station_agreement(stations: pd.DataFrame, days: int = 90) -> pd.DataFrame:
    """How well each station tracks the rest of its city over the last `days` days.

    A healthy station rises and falls with its neighbours (high correlation with the city median) and sits near it
    (small bias). A low correlation usually means a faulty or badly placed sensor rather than real local air.
    """
    s = stations[stations["date"] > stations["date"].max() - pd.Timedelta(days=days)].copy()
    s["city_median"] = s.groupby(["city", "date"])["aqi"].transform("median")
    out = []
    for (city, station), g in s.groupby(["city", "station"]):
        corr = g["aqi"].corr(g["city_median"]) if len(g) >= 20 else np.nan
        bias = (g["aqi"] - g["city_median"]).mean()
        if np.isnan(corr):
            verdict = "Too few days to judge"
        elif corr < 0.6:
            verdict = "Out of step with the city"
        elif abs(bias) >= 30:
            verdict = "Reads high" if bias > 0 else "Reads low"
        else:
            verdict = "Agrees with the city"
        out.append({"city": city, "station": station, "days": len(g), "correlation": corr, "bias": bias, "verdict": verdict})
    return pd.DataFrame(out)


def best_hours(profile: pd.DataFrame, city: str, month: int, n: int = 3) -> pd.DataFrame:
    """The n cleanest waking hours (6 am to 9 pm) in that city and month, from the hourly profile."""
    p = profile[(profile["city"] == city) & (profile["month"] == month) & profile["hour"].between(6, 21)]
    return p.nsmallest(n, "aqi")
