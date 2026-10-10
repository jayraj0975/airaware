"""Public API: city overview, stations, any area, model evaluation, insights, track record and citizen reports."""

import math
import os
import threading
import time
from datetime import date

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from airaware import live
from airaware.aqi import ADVICE, CATEGORIES, HEALTH_GROUPS, category, personal_advice
from airaware.data import CITIES, STATIONS
from airaware.insights import best_hours, cigarettes, diwali_effect, dominant, station_agreement
from airaware.model import AIRAWARE, HISTORY_ONLY, OPTIMISTIC, PERSISTENCE, TEST_FROM, p_text
from airaware.server import db
from airaware.server.auth import client_ip, current_user, require_user, visitor
from airaware.server.core import upcoming

router = APIRouter(prefix="/api")
REPORT_KINDS = {"burning": "Garbage or leaf burning", "construction": "Construction or road dust", "industry": "Factory smoke",
                "traffic": "Heavy traffic or idling", "firecrackers": "Firecrackers", "other": "Something else"}


def state(request: Request):
    return request.app.state.core


def clean(obj):
    """JSON-safe: numpy numbers to Python, NaN to None, timestamps to ISO strings."""
    if isinstance(obj, dict):
        return {k: clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    if isinstance(obj, np.integer):
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


def forecast_rows(fc: pd.DataFrame, groups=()) -> list[dict]:
    out = []
    for r in records(fc):
        r["date"], r["made_from"] = r["date"][:10], r["made_from"][:10]
        out.append({**r, "category": cat(r["forecast"]), "personal": personal_advice(r["forecast"], groups)})
    return out


def hour_shape(profile: pd.DataFrame, city: str, day: pd.Timestamp, daily_aqi: float) -> list[dict]:
    """The day's forecast spread over its hours with the city's usual daily pattern for that month.

    Each hour = daily forecast x (that hour's usual AQI / that month's usual daily mean). It is the typical shape of
    a day, scaled to the forecast, not an hourly model.
    """
    p = profile[(profile["city"] == city) & (profile["month"] == day.month)].sort_values("hour")
    if p.empty:
        return []
    scale = daily_aqi / p["aqi"].mean()
    return [{"hour": int(h), "aqi": float(a * scale)} for h, a in zip(p["hour"], p["aqi"])]


def check_city(city: str) -> str:
    if city not in CITIES:
        raise HTTPException(404, f"AirAware covers {', '.join(CITIES)}")
    return city


def groups_of(user: dict | None) -> list[str]:
    return [g for g in (user or {}).get("health", "").split(",") if g]


# ---------- rate limit for endpoints that call outside services ----------

AREA_PER_MINUTE = 30
MAX_VISITORS = 10_000
_hits: dict[str, list[float]] = {}
_hits_lock = threading.Lock()


def allow(client: str, per_minute: int = AREA_PER_MINUTE) -> bool:
    """Sliding one-minute window per visitor, remembering at most MAX_VISITORS (least recently seen dropped first).
    The memory bound is all this protects; the hard limit on outside calls is live.MIN_GAP."""
    now, key = time.time(), visitor(client)
    with _hits_lock:
        hits = [t for t in _hits.pop(key, []) if now - t < 60]
        ok = len(hits) < per_minute
        _hits[key] = hits + [now] if ok else hits
        while len(_hits) > MAX_VISITORS:
            _hits.pop(next(iter(_hits)))
        return ok


def limited(request: Request):
    if not allow(client_ip(request)):
        raise HTTPException(429, "Too many lookups. Wait a minute and try again.")


def weather(lat, lon):
    try:
        return live.weather_now(lat, lon)
    except OSError:
        return None


# ---------- endpoints ----------

@router.get("/status")
def status(request: Request):
    s = state(request)
    with s.lock:
        last = s.daily.dropna(subset=["aqi"]).groupby("city")["date"].max()
        trained = s.trained_at
    return clean({"cities": {c: {"lat": ll[0], "lon": ll[1], "last_measured": last[c].date().isoformat(),
                                 "stations": len(set(STATIONS[c].values()))} for c, ll in CITIES.items()},
                  "trained_at": trained, "live_readings": not s.live.empty, "live_at": s.live_at,
                  "live_key": bool(os.environ.get("OPENAQ_API_KEY")),
                  "categories": [{"upper": None if math.isinf(u) else u, "name": n, "colour": c, "advice": ADVICE[n]} for u, n, c in CATEGORIES],
                  "health_groups": HEALTH_GROUPS, "report_kinds": REPORT_KINDS})


def personal(response: Response, user: dict | None) -> None:
    """Marks a response that depends on who is signed in, so the service worker never caches it (see sw.js)."""
    if user:
        response.headers["X-AirAware-Personal"] = "1"


@router.get("/overview")
def overview(request: Request, response: Response, city: str = "Pune", user: dict | None = Depends(current_user)):
    check_city(city)
    personal(response, user)
    s = state(request)
    with s.lock:
        d = s.forecast_daily[s.forecast_daily["city"] == city]
        measured = d.dropna(subset=["aqi"]).iloc[-1]
        fc = s.forecast[s.forecast["city"] == city]
        hist = d[d["date"] > measured["date"] - pd.Timedelta(days=42)].dropna(subset=["aqi"])
        profile = s.profile
    ahead = upcoming(fc)
    best = ahead.loc[ahead["forecast"].idxmin()]
    first = ahead.iloc[0]
    return clean({
        "hours": hour_shape(profile, city, first["date"], first["forecast"]),
        "city": city,
        "measured": {"date": measured["date"].date().isoformat(), "aqi": measured["aqi"], "pm25": measured["pm25"], "pm10": measured["pm10"],
                     "stations": measured["stations"], "category": cat(measured["aqi"]),
                     "dominant": dominant(pd.Series([measured["pm25"]]), pd.Series([measured["pm10"]]))[0],
                     "cigarettes": cigarettes(measured["pm25"]), "source": "live" if measured["date"] == pd.Timestamp(date.today()) else "archive"},
        "forecast": forecast_rows(fc, groups_of(user)),
        "history": [{"date": t.date().isoformat(), "aqi": a} for t, a in zip(hist["date"], hist["aqi"])],
        "plan": {"best_day": best["date"].date().isoformat(), "best_day_aqi": best["forecast"],
                 "best_hours": sorted(best_hours(profile, city, best["date"].month)["hour"].tolist())},
        "weather": weather(*CITIES[city]),
    })


@router.get("/stations")
def stations_api(request: Request, city: str = "Pune"):
    check_city(city)
    s = state(request)
    with s.lock:
        st, source = s.latest_stations(city)
        trust = station_agreement(s.stations)
    st = st.merge(trust[["station", "verdict", "correlation"]], on="station", how="left")
    return {"source": source, "stations": [{**r, "category": cat(r["aqi"])} for r in records(
        st[["station", "lat", "lon", "date", "aqi", "pm25", "pm10", "verdict", "correlation"]].assign(date=st["date"].astype(str).str[:16]))]}


@router.get("/area", dependencies=[Depends(limited)])
def area(request: Request, response: Response, lat: float = Query(ge=-90, le=90), lon: float = Query(ge=-180, le=180),
         user: dict | None = Depends(current_user)):
    """Everything about one point: estimated AQI, its forecast, weather now, nearest stations and recent reports."""
    personal(response, user)
    a = state(request).area(lat, lon)
    if a is None:  # say how far, and which city is nearest, so the page can offer that city instead of a dead end
        city, km = live.nearest_city(lat, lon)
        raise HTTPException(404, {"message": f"That spot is about {km:.0f} km from {city}. AirAware covers the Pune and Mumbai areas, "
                                             "up to about 60 km from each city.", "outside": True, "nearest_city": city, "km": round(km)})
    fc = a["forecast"]
    rows = forecast_rows(fc, groups_of(user))
    now = forecast_rows(upcoming(fc).head(1), groups_of(user))[0]
    est = a["estimate"]
    nearby = nearby_reports(lat, lon, km=3)
    with state(request).lock:
        profile = state(request).profile
    return clean({
        "lat": lat, "lon": lon, "city": a["city"], "place": live.place_name(lat, lon), "source": a["source"],
        "measured": {**est, "category": cat(est["aqi"]), "offset": a["offset"]},
        "today": now, "forecast": rows,
        "best_hours": sorted(best_hours(profile, a["city"], date.today().month)["hour"].tolist()),
        "hours": hour_shape(profile, a["city"], pd.Timestamp(now["date"]), now["forecast"]),
        "weather": weather(lat, lon), "reports": nearby,
    })


@router.get("/search", dependencies=[Depends(limited)])
def search(q: str = Query(min_length=2, max_length=80), city: str = "Pune"):
    """Find an area by name, within the chosen city."""
    check_city(city)
    try:
        return live.search_places(q, city)
    except (OSError, ValueError):
        raise HTTPException(503, "Place search is busy. Try again in a moment, or click the map.")


@router.get("/model")
def model_api(request: Request):
    r = state(request).result
    both = r.table[r.table["City"] == "Both"].drop(columns="City")
    by_city = r.table.pivot(index="Method", columns="City", values="MAE").reset_index()
    return clean({
        "test_from": TEST_FROM.date().isoformat(), "forecasts": len(r.test), "airaware": AIRAWARE, "persistence": PERSISTENCE,
        "history_only": HISTORY_ONLY, "optimistic": OPTIMISTIC, "vintage": r.vintage,
        "table": records(both.rename(columns={"Category accuracy": "category_accuracy", "Poor-day recall": "poor_recall"})),
        "by_city": records(by_city),
        "dm": {"statistic": r.dm[0], "p": r.dm[1], "text": p_text(r.dm[1])},
        "dm_history": {"statistic": r.dm_history[0], "p": r.dm_history[1], "text": p_text(r.dm_history[1])},
        "horizons": records(r.horizons.rename(columns={"Days ahead": "h", "80% range coverage": "coverage", "DM p vs persistence": "dm_p"})),
        "importance": [{"feature": f, "value": v} for f, v in r.importance.head(12).items()],
    })


@router.get("/insights")
def insights_api(request: Request, city: str = "Pune"):
    check_city(city)
    s = state(request)
    with s.lock:
        d, profile = s.daily, s.profile
    p = profile[profile["city"] == city]
    dw = diwali_effect(d)
    dw = dw[dw["city"] == city]
    ok = d[d["city"] == city].dropna(subset=["aqi", "pm25", "pm10"])
    dom = ok.assign(p=dominant(ok["pm25"], ok["pm10"]) == "PM2.5").groupby(ok["date"].dt.month)["p"].mean()
    year = d[(d["city"] == city) & (d["date"] > d.dropna(subset=["pm25"])["date"].max() - pd.Timedelta(days=365))].dropna(subset=["pm25"])
    weekday = ok.groupby(ok["date"].dt.dayofweek)["aqi"].mean()
    return clean({
        "hourly": records(p[["month", "hour", "aqi", "pm25", "pm10"]]),
        "diwali": {"curve": [{"offset": k, "change": v} for k, v in dw.groupby("offset")["change"].mean().items()],
                   "years": sorted(dw["year"].unique().tolist())},
        "pm25_share": [{"month": m, "share": v} for m, v in dom.items()],
        "monthly": [{"month": m, "aqi": v} for m, v in ok.groupby(ok["date"].dt.month)["aqi"].mean().items()],
        "weekday": [{"day": int(k), "aqi": v} for k, v in weekday.items()],
        "cigarettes_year": cigarettes(year["pm25"].mean()) * 365 if len(year) else None,
        "days": len(ok), "since": ok["date"].min().date().isoformat(),
    })


@router.get("/track-record")
def track_record(city: str | None = None):
    """Every forecast the site has published, scored against the real AQI once it is measured."""
    where, args = ("WHERE city = ?", (city,)) if city else ("", ())
    scored = db.rows(f"SELECT * FROM forecast_log {where} {'AND' if city else 'WHERE'} actual IS NOT NULL ORDER BY target DESC", args)
    pending = db.one(f"SELECT COUNT(*) AS n FROM forecast_log {where} {'AND' if city else 'WHERE'} actual IS NULL", args)["n"]
    by_h = {}
    for r in scored:
        h = by_h.setdefault(r["days_ahead"], {"n": 0, "err": 0.0, "base": 0.0, "inside": 0})
        h["n"] += 1
        h["err"] += abs(r["forecast"] - r["actual"])
        h["base"] += abs(r["persistence"] - r["actual"])
        h["inside"] += r["lo"] <= r["actual"] <= r["hi"]
    return clean({
        "scored": len(scored), "pending": pending,
        "horizons": [{"h": h, "n": v["n"], "mae": v["err"] / v["n"], "persistence_mae": v["base"] / v["n"], "coverage": v["inside"] / v["n"]}
                     for h, v in sorted(by_h.items())],
        "recent": scored[:60],
    })


# ---------- citizen reports ----------

def nearby_reports(lat: float, lon: float, km: float = 3, days: int = 7) -> list[dict]:
    since = (pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=days)).isoformat(timespec="seconds")
    near = db.rows("""SELECT id, lat, lon, kind, note, created_at FROM reports WHERE status = 'approved' AND created_at >= ?
                      AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ? ORDER BY created_at DESC LIMIT 50""",
                   (since, lat - km / 111, lat + km / 111, lon - km / 105, lon + km / 105))
    return [{**r, "label": REPORT_KINDS.get(r["kind"], r["kind"])} for r in near]


@router.get("/reports")
def list_reports(city: str = "Pune", days: int = Query(14, ge=1, le=90)):
    check_city(city)
    since = (pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=days)).isoformat(timespec="seconds")
    rs = db.rows("""SELECT id, lat, lon, kind, note, created_at FROM reports
                    WHERE status = 'approved' AND city = ? AND created_at >= ? ORDER BY created_at DESC LIMIT 300""", (city, since))
    return [{**r, "label": REPORT_KINDS.get(r["kind"], r["kind"])} for r in rs]


class NewReport(BaseModel):
    lat: float = Field(ge=-90, le=90, allow_inf_nan=False)
    lon: float = Field(ge=-180, le=180, allow_inf_nan=False)
    kind: str = Field(max_length=20)
    note: str = Field("", max_length=280)


@router.post("/reports", status_code=201)
def create_report(request: Request, body: NewReport, user: dict = Depends(require_user)):
    """A signed-in user reports a pollution source; it shows on the map once an admin approves it."""
    lat, lon, kind, note = body.lat, body.lon, body.kind, body.note.strip()
    if kind not in REPORT_KINDS:
        raise HTTPException(422, f"kind must be one of {', '.join(REPORT_KINDS)}")
    city, km = live.nearest_city(lat, lon)
    if km > 60:
        raise HTTPException(422, "Reports must be in the Pune or Mumbai area.")
    recent = db.one("SELECT COUNT(*) AS n FROM reports WHERE user_id = ? AND created_at >= ?",
                    (user["id"], (pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=1)).isoformat(timespec="seconds")))["n"]
    if recent >= 10:
        raise HTTPException(429, "That's a lot of reports in an hour. Try again later.")
    rid = db.run("INSERT INTO reports (user_id, lat, lon, city, kind, note, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                 (user["id"], lat, lon, city, kind, note[:280], db.now()))
    db.audit("report.create", user["id"], f"report {rid} {kind} in {city}")
    return {"id": rid, "status": "pending"}
