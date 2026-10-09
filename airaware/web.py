"""AirAware website: `uvicorn airaware.web:app` serves the JSON API under /api and the dashboard from web/.

A background thread keeps the data fresh: station archive, weather and CAMS forecasts every few hours (then the models
retrain), and live CPCB readings every hour when OPENAQ_API_KEY is set.
"""

import ipaddress
import math
import os
import threading
import time
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from airaware import live
from airaware.aqi import ADVICE, CATEGORIES, category
from airaware.data import CITIES, STATIONS, build, load, load_hourly, load_stations, save
from airaware.insights import best_hours, cigarettes, diwali_effect, dominant, station_agreement
from airaware.model import AIRAWARE, PERSISTENCE, TEST_FROM, forecast_now, p_text, train

WEB = Path(__file__).resolve().parent.parent / "web"
REBUILD_HOURS = float(os.environ.get("AIRAWARE_REBUILD_HOURS", 6))
LIVE_MINUTES = 60


class State:
    """Everything the API serves, swapped in whole after each refresh so requests never see half an update."""

    def __init__(self):
        self.lock = threading.Lock()
        self.live = pd.DataFrame()  # live station readings from OpenAQ, when a key is set
        self.live_at = None
        self.load()

    def load(self):
        daily, stations, profile = load(), load_stations(), load_hourly()
        result = train(daily)
        with self.lock:
            self.daily, self.stations, self.profile, self.result = daily, stations, profile, result
            self.trained_at = pd.Timestamp.now(tz=live.TZ)
            self._forecast()

    def _forecast(self):
        """Forecast from live readings when they exist (a true next-day forecast), otherwise from the archive."""
        daily = self.daily
        if not self.live.empty:
            daily = with_live_day(daily, self.live, self.stations)
        self.forecast = forecast_now(daily, self.result)
        self.forecast_daily = daily

    def set_live(self, readings: pd.DataFrame):
        with self.lock:
            self.live, self.live_at = readings, pd.Timestamp.now(tz=live.TZ)
            self._forecast()


def with_live_day(daily: pd.DataFrame, readings: pd.DataFrame, stations: pd.DataFrame) -> pd.DataFrame:
    """Add today's city AQI from live 24-hour station averages, so the forecast starts from today."""
    city_of = stations.drop_duplicates("station").set_index("station")["city"]
    r = readings.assign(city=readings["station"].map(city_of)).dropna(subset=["city", "aqi"])
    today = pd.Timestamp(date.today())
    d = daily.copy()
    for city, g in r.groupby("city"):
        if len(g) < 2:  # same rule as the archive: a city value needs two stations
            continue
        row = (d["city"] == city) & (d["date"] == today)
        d.loc[row, ["aqi", "pm25", "pm10", "stations"]] = [g["aqi"].mean(), g["pm25"].mean(), g["pm10"].mean(), len(g)]
    return d


state: State | None = None


def refresher():
    """Rebuild from the archive every REBUILD_HOURS and pull live readings every hour; failures keep the old data."""
    last_build = time.time()
    while True:
        if os.environ.get("OPENAQ_API_KEY"):
            try:
                readings = live.openaq_latest({loc: name for c in STATIONS.values() for loc, name in c.items()})
                if not readings.empty:
                    state.set_live(readings)
            except OSError:
                pass
        if time.time() - last_build >= REBUILD_HOURS * 3600:
            try:
                save(*build())
                state.load()
            except OSError:
                pass
            last_build = time.time()
        time.sleep(LIVE_MINUTES * 60)


@asynccontextmanager
async def lifespan(_):
    global state
    state = State()
    if os.environ.get("AIRAWARE_REFRESH", "1") == "1":
        threading.Thread(target=refresher, daemon=True).start()
    yield


app = FastAPI(title="AirAware", lifespan=lifespan)


def clean(obj):
    """JSON-safe: numpy numbers to Python, NaN to None, timestamps to ISO strings."""
    if isinstance(obj, dict):
        return {k: clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        return None if math.isnan(obj) else round(float(obj), 4)
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    return obj


def records(df: pd.DataFrame) -> list[dict]:
    return clean(df.to_dict(orient="records"))


def cat(value: float) -> dict:
    name, colour = category(value)
    return {"name": name, "colour": colour, "advice": ADVICE[name]}


def check_city(city: str) -> str:
    if city not in CITIES:
        raise HTTPException(404, f"AirAware covers {', '.join(CITIES)}")
    return city


def latest_stations(city: str) -> tuple[pd.DataFrame, str]:
    """Each station's newest reading: live when available, else its last archive day within a week of the city's."""
    if not state.live.empty:
        lv = state.live.merge(state.stations.drop_duplicates("station")[["station", "city"]], on="station")
        lv = lv[lv["city"] == city]
        if len(lv) >= 2:
            return lv.assign(date=lv["last"].str[:16]), "live"
    s = state.stations[state.stations["city"] == city]
    s = s[s["date"] > s["date"].max() - pd.Timedelta(days=7)].sort_values("date").drop_duplicates("station", keep="last")
    return s, "archive"


@app.get("/api/status")
def status():
    with state.lock:
        last = state.daily.dropna(subset=["aqi"]).groupby("city")["date"].max()
        return clean({"cities": {c: {"lat": ll[0], "lon": ll[1], "last_measured": last[c].date().isoformat(),
                                     "stations": len(set(STATIONS[c].values()))} for c, ll in CITIES.items()},
                      "trained_at": state.trained_at, "live_readings": not state.live.empty, "live_at": state.live_at,
                      "live_key": bool(os.environ.get("OPENAQ_API_KEY")),
                      "categories": [{"upper": None if math.isinf(u) else u, "name": n, "colour": c} for u, n, c in CATEGORIES]})


@app.get("/api/overview")
def overview(city: str = "Pune"):
    check_city(city)
    with state.lock:
        d = state.forecast_daily[(state.forecast_daily["city"] == city)]
        measured = d.dropna(subset=["aqi"]).iloc[-1]
        fc = state.forecast[state.forecast["city"] == city]
        hist = d[d["date"] > measured["date"] - pd.Timedelta(days=42)].dropna(subset=["aqi"])
        profile = state.profile
    today = pd.Timestamp(date.today())
    upcoming = fc[fc["date"] >= today]
    upcoming = upcoming if not upcoming.empty else fc
    best = upcoming.loc[upcoming["forecast"].idxmin()]
    lat, lon = CITIES[city]
    try:
        weather = live.weather_now(lat, lon)
    except OSError:
        weather = None
    return clean({
        "city": city,
        "measured": {"date": measured["date"].date().isoformat(), "aqi": measured["aqi"], "pm25": measured["pm25"], "pm10": measured["pm10"],
                     "stations": measured["stations"], "category": cat(measured["aqi"]),
                     "dominant": dominant(pd.Series([measured["pm25"]]), pd.Series([measured["pm10"]]))[0],
                     "cigarettes": cigarettes(measured["pm25"]), "source": "live" if measured["date"] == today else "archive"},
        "forecast": [{**r, "date": r["date"][:10], "made_from": r["made_from"][:10], "category": cat(r["forecast"])} for r in records(fc)],
        "history": [{"date": t.date().isoformat(), "aqi": a} for t, a in zip(hist["date"], hist["aqi"])],
        "plan": {"best_day": best["date"].date().isoformat(), "best_day_aqi": best["forecast"],
                 "best_hours": sorted(best_hours(profile, city, best["date"].month)["hour"].tolist())},
        "weather": weather,
    })


@app.get("/api/stations")
def stations_api(city: str = "Pune"):
    check_city(city)
    with state.lock:
        s, source = latest_stations(city)
        trust = station_agreement(state.stations)
    s = s.merge(trust[["station", "verdict", "correlation"]], on="station", how="left")
    return {"source": source, "stations": [{**r, "category": cat(r["aqi"])} for r in records(
        s[["station", "lat", "lon", "date", "aqi", "pm25", "pm10", "verdict", "correlation"]].assign(date=s["date"].astype(str).str[:16]))]}


AREA_PER_MINUTE = 30
MAX_VISITORS = 10_000
_area_hits: dict[str, list[float]] = {}
_area_lock = threading.Lock()


def visitor(host: str) -> str:
    """The rate-limit key for an address. An IPv6 user usually controls a whole /64, so that is one visitor."""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return host
    return str(ipaddress.ip_network(f"{ip}/64", strict=False)) if ip.version == 6 else str(ip)


def allow_area(client: str) -> bool:
    """At most AREA_PER_MINUTE area lookups a minute per visitor, so one device cannot use up the shared
    allowance for outside services (see live.MIN_GAP) and leave everyone else without weather or place names.

    Remembers at most MAX_VISITORS visitors, dropping the least recently seen. That bound is for memory only: the
    hard limit on calls to outside services is live.MIN_GAP, which holds however many addresses a client uses.
    """
    now, key = time.time(), visitor(client)
    with _area_lock:
        hits = [t for t in _area_hits.pop(key, []) if now - t < 60]
        allowed = len(hits) < AREA_PER_MINUTE
        _area_hits[key] = hits + [now] if allowed else hits  # re-inserted, so the dict stays ordered by last seen
        while len(_area_hits) > MAX_VISITORS:
            _area_hits.pop(next(iter(_area_hits)))
        return allowed


@app.get("/api/area")
def area(request: Request, lat: float = Query(ge=-90, le=90), lon: float = Query(ge=-180, le=180)):
    """Everything about one point on the map: estimated AQI, its forecast, weather now and the nearest stations."""
    if not allow_area(request.client.host if request.client else "?"):
        raise HTTPException(429, "Too many area lookups. Wait a minute and try again.")
    city, km = live.nearest_city(lat, lon)
    if km > 60:
        raise HTTPException(404, "AirAware covers the Pune and Mumbai areas. Click closer to one of them.")
    with state.lock:
        s, source = latest_stations(city)
        fc = state.forecast[state.forecast["city"] == city]
        profile = state.profile
    est = live.idw(s, lat, lon)
    offset = est["aqi"] - float(s["aqi"].mean())  # how this spot compares with the city's stations on their latest day
    area_fc = fc.assign(forecast=(fc["forecast"] + offset).clip(lower=0), lo=(fc["lo"] + offset).clip(lower=0), hi=fc["hi"] + offset)
    today = pd.Timestamp(date.today())
    nowish = area_fc[area_fc["date"] >= today].head(1)
    nowish = nowish if not nowish.empty else area_fc.tail(1)
    try:
        weather = live.weather_now(lat, lon)
    except OSError:
        weather = None
    return clean({
        "lat": lat, "lon": lon, "city": city, "place": live.place_name(lat, lon), "source": source,
        "measured": {**est, "category": cat(est["aqi"]), "offset": offset},
        "today": {**(t := records(nowish)[0]), "date": t["date"][:10], "category": cat(float(nowish["forecast"].iloc[0]))},
        "forecast": [{**r, "date": r["date"][:10], "category": cat(r["forecast"])} for r in records(area_fc)],
        "best_hours": sorted(best_hours(profile, city, today.month)["hour"].tolist()),
        "weather": weather,
    })


@app.get("/api/model")
def model_api():
    with state.lock:
        r = state.result
    both = r.table[r.table["City"] == "Both"].drop(columns="City")
    by_city = r.table.pivot(index="Method", columns="City", values="MAE").reset_index()
    imp = r.importance.head(10)
    return clean({
        "test_from": TEST_FROM.date().isoformat(), "forecasts": len(r.test), "airaware": AIRAWARE, "persistence": PERSISTENCE,
        "table": records(both.rename(columns={"Category accuracy": "category_accuracy", "Poor-day recall": "poor_recall"})),
        "by_city": records(by_city),
        "dm": {"statistic": r.dm[0], "p": r.dm[1], "text": p_text(r.dm[1])},
        "horizons": records(r.horizons.rename(columns={"Days ahead": "h", "80% range coverage": "coverage"})),
        "importance": [{"feature": f, "value": v} for f, v in imp.items()],
    })


@app.get("/api/insights")
def insights_api(city: str = "Pune"):
    check_city(city)
    with state.lock:
        d, profile = state.daily, state.profile
    p = profile[profile["city"] == city]
    dw = diwali_effect(d)
    dw = dw[dw["city"] == city]
    ok = d[d["city"] == city].dropna(subset=["aqi", "pm25", "pm10"])
    dom = ok.assign(p=dominant(ok["pm25"], ok["pm10"]) == "PM2.5").groupby(ok["date"].dt.month)["p"].mean()
    year = d[(d["city"] == city) & (d["date"] > d.dropna(subset=["pm25"])["date"].max() - pd.Timedelta(days=365))].dropna(subset=["pm25"])
    monthly = ok.groupby(ok["date"].dt.month)["aqi"].mean()
    return clean({
        "hourly": records(p[["month", "hour", "aqi", "pm25", "pm10"]]),
        "diwali": {"curve": [{"offset": k, "change": v} for k, v in dw.groupby("offset")["change"].mean().items()],
                   "years": sorted(dw["year"].unique().tolist())},
        "pm25_share": [{"month": m, "share": v} for m, v in dom.items()],
        "monthly": [{"month": m, "aqi": v} for m, v in monthly.items()],
        "cigarettes_year": cigarettes(year["pm25"].mean()) * 365 if len(year) else None,
    })


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


app.mount("/static", StaticFiles(directory=WEB), name="static")
