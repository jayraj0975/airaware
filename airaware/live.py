"""Live data: weather now, estimates for any point on the map, and optional live CPCB readings.

Sources, all free:
- Open-Meteo forecast API: current weather and the next two days, no key.
- OpenAQ v3 API: the latest hourly CPCB readings, only when OPENAQ_API_KEY is set (free key from explore.openaq.org).
- OpenStreetMap Nominatim: the name of the area at a clicked point.
"""

import json
import math
import os
import threading
import time
import urllib.parse
import urllib.request

import numpy as np
import pandas as pd

from airaware.aqi import sub_index
from airaware.data import CITIES, TZ, _url

WX_API = "https://api.open-meteo.com/v1/forecast"
GEOCODE = "https://nominatim.openstreetmap.org/reverse"
SEARCH = "https://nominatim.openstreetmap.org/search"
OPENAQ = "https://api.openaq.org/v3"
USER_AGENT = "AirAware/1.0 (college air-quality project)"

CACHE_SIZE = 2000
# Fewest seconds between calls to each outside service, shared by all visitors, so a flood of map clicks cannot be
# turned into a flood of requests to them (see _json). Nominatim's usage policy allows at most one request a second.
MIN_GAP = {"nominatim.openstreetmap.org": 1.0, "api.open-meteo.com": 0.2, "api.openaq.org": 0.0}

_cache: dict = {}
_last_call: dict = {}
_lock = threading.Lock()


def cached(key, seconds: int, fetch):
    """Keep a fetched value for `seconds`; on a failed or throttled refresh keep serving the old value.

    Holds at most CACHE_SIZE entries, dropping the oldest first.
    """
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < seconds:
        return hit[1]
    try:
        value = fetch()
    except OSError:
        if hit:
            return hit[1]
        raise
    with _lock:
        _cache.pop(key, None)
        _cache[key] = (time.time(), value)
        while len(_cache) > CACHE_SIZE:
            _cache.pop(next(iter(_cache)))  # dicts keep insertion order, so this is the oldest
    return value


class Throttled(OSError):
    """Too soon after the last call to this service; callers treat it like a network failure."""


MAX_WAIT = 2.0  # seconds a call may queue for its turn before it is refused


def _json(url: str, params: dict, headers: dict | None = None) -> dict:
    """GET a JSON API, spacing calls to each host by MIN_GAP.

    Each call books the next free slot for its host and waits for it, so a burst of page loads is served a moment
    later instead of failing; a call whose slot is more than MAX_WAIT away is refused (Throttled).
    """
    host = urllib.parse.urlsplit(url).hostname
    with _lock:
        now = time.time()
        slot = max(now, _last_call.get(host, 0) + MIN_GAP.get(host, 0.5))
        if slot - now > MAX_WAIT:
            raise Throttled(f"too many requests to {host}")
        _last_call[host] = slot
    if slot > now:
        time.sleep(slot - now)
    req = urllib.request.Request(f"{url}?{urllib.parse.urlencode(params)}", headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=10) as r:  # short, so a slow service cannot tie up the server's threads
        return json.loads(r.read())


def aqi_of(pm25: float, pm10: float) -> float:
    return float(np.fmax(sub_index("pm2_5", pm25), sub_index("pm10", pm10)))


def distance_km(lat1, lon1, lat2, lon2):
    """Great-circle distance; works on numbers or numpy arrays."""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(np.radians(lon2 - lon1) / 2) ** 2
    return 6371 * 2 * np.arcsin(np.sqrt(a))


def nearest_city(lat: float, lon: float) -> tuple[str, float]:
    return min(((c, float(distance_km(lat, lon, *ll))) for c, ll in CITIES.items()), key=lambda t: t[1])


# ---------- weather ----------

def weather_now(lat: float, lon: float) -> dict:
    """Current conditions plus the next 48 hours."""
    def fetch():
        j = _json(WX_API, {"latitude": round(lat, 2), "longitude": round(lon, 2), "timezone": TZ, "forecast_days": 3,
                           "current": "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,"
                                      "wind_speed_10m,wind_direction_10m,surface_pressure",
                           "hourly": "temperature_2m,relative_humidity_2m,precipitation_probability,wind_speed_10m,boundary_layer_height"})
        h = pd.DataFrame(j["hourly"])
        h = h[pd.to_datetime(h["time"]) >= pd.Timestamp(j["current"]["time"]).floor("h")].head(48)
        return {"current": j["current"], "hourly": h.to_dict(orient="list")}
    return cached(("wx", round(lat, 2), round(lon, 2)), 900, fetch)  # weather does not change within ~1 km


# ---------- any point on the map ----------

def idw(stations: pd.DataFrame, lat: float, lon: float, radius_km: float = 12, power: float = 2) -> dict:
    """Inverse-distance-weighted AQI at a point from stations within `radius_km`, plus the nearest stations.

    A station on top of the point (under 0.3 km) is taken as is. With no station in range, falls back to the nearest one.
    """
    s = stations.dropna(subset=["aqi"]).copy()
    s["km"] = distance_km(lat, lon, s["lat"].to_numpy(), s["lon"].to_numpy())
    s = s.sort_values("km")
    near = s[s["km"] <= radius_km]
    if near.empty:
        near = s.head(1)
    if near["km"].iloc[0] < 0.3:
        value = float(near["aqi"].iloc[0])
    else:
        w = 1 / near["km"] ** power
        value = float((w * near["aqi"]).sum() / w.sum())
    return {"aqi": round(value, 1), "used": len(near),
            "nearest": s.head(4)[["station", "km", "aqi", "date"]].assign(km=lambda t: t["km"].round(1), aqi=lambda t: t["aqi"].round(0),
                                                                          date=lambda t: t["date"].astype(str)).to_dict(orient="records")}


def place_name(lat: float, lon: float) -> str:
    """The neighbourhood at a point, from OpenStreetMap; empty if the lookup fails."""
    def fetch():
        a = _json(GEOCODE, {"lat": round(lat, 3), "lon": round(lon, 3), "format": "jsonv2", "zoom": 15}).get("address", {})
        suburb = a.get("suburb", "")
        if suburb.lower().endswith("ward"):  # Mumbai's municipal wards ("H/W Ward") mean little to people
            suburb = ""
        local = suburb or a.get("neighbourhood") or a.get("quarter") or a.get("locality") or a.get("village") or a.get("town") or a.get("suburb")
        return ", ".join(dict.fromkeys(x for x in [local, a.get("city") or a.get("county")] if x))
    try:
        return cached(("geo", round(lat, 3), round(lon, 3)), 86400, fetch)
    except (OSError, ValueError):
        return ""


# ---------- optional live CPCB readings via OpenAQ ----------

def openaq_latest(locations: dict[int, str], key: str | None = None, pause: float = 1.1) -> pd.DataFrame:
    """The last 24 hours of hourly PM2.5/PM10 for each station and its 24-hour AQI, from OpenAQ's live API.

    Needs OPENAQ_API_KEY. About three calls per station, paced under the free tier's 60 calls a minute.
    """
    key = key or os.environ.get("OPENAQ_API_KEY")
    if not key:
        return pd.DataFrame()
    headers = {"X-API-Key": key}
    since = (pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = []
    for loc, name in locations.items():
        try:
            meta = _json(f"{OPENAQ}/locations/{loc}", {}, headers)["results"][0]
            time.sleep(pause)
            last_seen = (meta.get("datetimeLast") or {}).get("utc")
            if last_seen and last_seen < since:
                continue  # nothing in the window (a retired id, or the feed is paused): skip its sensor calls
            means = {}
            for sensor in meta.get("sensors", []):
                param = sensor["parameter"]["name"]
                if param not in ("pm25", "pm10"):
                    continue
                hours = _json(f"{OPENAQ}/sensors/{sensor['id']}/hours", {"datetime_from": since, "limit": 48}, headers)["results"]
                time.sleep(pause)
                means[param], means[param + "_n"] = _hourly_mean(hours)
                means["last"] = max(means.get("last", ""), max((h["period"]["datetimeTo"]["local"] for h in hours), default=""))
            if means.get("pm25_n", 0) >= 16 or means.get("pm10_n", 0) >= 16:
                rows.append({"station": name, "lat": meta["coordinates"]["latitude"], "lon": meta["coordinates"]["longitude"],
                             "pm25": means.get("pm25"), "pm10": means.get("pm10"), "last": means["last"],
                             "aqi": aqi_of(means.get("pm25", math.nan), means.get("pm10", math.nan))})
        except (OSError, KeyError, IndexError, ValueError):
            continue  # one station failing must not stop the rest
    return pd.DataFrame(rows)


def _hourly_mean(hours: list[dict]) -> tuple[float, int]:
    """Mean of valid hourly values (same error codes and limits as the archive cleaning)."""
    v = [h["value"] for h in hours if h.get("value") is not None and 0 < h["value"] < 985]
    return (float(np.mean(v)) if v else math.nan), len(v)


def search_places(query: str, city: str, limit: int = 6) -> list[dict]:
    """Places matching `query` inside the city's area, from OpenStreetMap, cached for a day."""
    lat, lon = CITIES[city]
    box = f"{lon - 0.4},{lat + 0.35},{lon + 0.4},{lat - 0.35}"  # west, north, east, south: about 80 x 80 km

    def fetch():
        found = _json(SEARCH, {"q": query, "format": "jsonv2", "limit": 15, "viewbox": box, "bounded": 1, "addressdetails": 0})
        q = query.strip().lower()
        def rank(r):  # localities first, then roads and stations, then single buildings; exact names first in each
            kind = r.get("category", "")
            group = 0 if kind in ("place", "boundary") or (kind == "landuse" and r.get("type") == "residential") else \
                1 if kind in ("highway", "railway") else 2
            return group, r.get("name", "").lower() != q, -float(r.get("importance") or 0)
        out = []
        for r in sorted(found, key=rank):
            parts = [p.strip() for p in r.get("display_name", "").split(",")]
            name, area = parts[0], ", ".join(p for p in parts[1:3] if p and not p.isdigit())
            lat_, lon_ = float(r["lat"]), float(r["lon"])
            if len(name) < 3 or any(o["name"].lower() == name.lower() and abs(o["lat"] - lat_) < 0.02 and abs(o["lon"] - lon_) < 0.02 for o in out):
                continue  # one entry per place: the same name within about 2 km is the same place
            out.append({"name": name, "area": area, "lat": lat_, "lon": lon_})
        return out[:limit]
    return cached(("search", city, query.strip().lower()), 86400, fetch)
