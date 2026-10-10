"""Real CPCB station readings (OpenAQ's public archive) + weather (ERA5 via Open-Meteo) -> one row per city-day.

Run `python -m airaware.data` to refresh data/daily.csv. No accounts or API keys are needed; the first run
downloads ~40k small files and takes a few minutes, later runs fetch only the new days.
"""

import csv
import gzip
import io
import json
import re
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from airaware.aqi import sub_index

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
DAILY_CSV = ROOT / "data" / "daily.csv"
STATIONS_CSV = ROOT / "data" / "stations.csv"
HOURLY_CSV = ROOT / "data" / "hourly_profile.csv"
VINTAGE_CSV = ROOT / "data" / "forecast_vintage.csv"
COORDS = RAW / "coords.json"
TZ = "Asia/Kolkata"
START = "2020-11-14"  # first full day of the IITM stations

CITIES = {"Pune": (18.5204, 73.8567), "Mumbai": (19.0760, 72.8777)}
# OpenAQ location ids of the CPCB continuous monitors inside each city (Pune includes Pimpri-Chinchwad;
# Navi Mumbai and Vasai left out of Mumbai). Found by scanning the archive's location ids for coordinates in each city.
# OpenAQ re-listed many stations under new ids in February 2025; both ids are kept, and a station's
# old and new ids are merged by name before averaging.
STATIONS = {
    "Pune": {11608: "Bhosari", 11609: "Mhada Colony", 11610: "Transport Nagar-Nigdi", 11613: "Revenue Colony-Shivajinagar",
             3409331: "Bhosari", 3409438: "Katraj Dairy", 3409439: "Savitribai Phule Pune University",
             3409523: "Bhumkar Nagar", 3409526: "Panchawati-Pashan", 3410005: "Dhankawadi", 12042: "Alandi",
             # Pimpri-Chinchwad, the twin city inside the Pune metro area
             3409435: "Gavalinagar (PCMC)", 3409436: "Park Street Wakad (PCMC)", 3409437: "Thergaon (PCMC)",
             3409528: "Savta Mali Nagar (PCMC)"},
    "Mumbai": {6927: "Colaba", 6945: "Kurla", 6948: "Airport T2", 6956: "Powai", 6959: "Worli", 6965: "Borivali East (MPCB)",
               6967: "Sion", 6987: "Vile Parle West", 11600: "Mazgaon", 11602: "Bandra Kurla Complex (IITM)", 11604: "Deonar",
               11605: "Navy Nagar-Colaba", 11606: "Borivali East (IITM)", 11611: "Malad West",
               3409323: "Worli", 3409328: "Bandra Kurla Complex (IITM)", 3409329: "Deonar", 3409479: "Mindspace-Malad West",
               3409482: "Bandra Kurla Complex (MPCB)", 3409483: "Chembur", 3409486: "Kherwadi-Bandra East", 3409510: "Byculla",
               3409511: "Shivaji Nagar", 3409512: "Kandivali West", 3409513: "Sewri", 3409514: "Ghatkopar"},
}

ARCHIVE = "https://openaq-data-archive.s3.amazonaws.com"
WX_HISTORY = "https://archive-api.open-meteo.com/v1/archive"
WX_FORECAST = "https://api.open-meteo.com/v1/forecast"
CAMS_API = "https://air-quality-api.open-meteo.com/v1/air-quality"
WX_PREVIOUS = "https://previous-runs-api.open-meteo.com/v1/forecast"  # forecasts as issued 1-7 days before
VINTAGE_START = "2024-06-01"  # the archive of issued forecasts starts in mid-2024
LEADS = range(1, 8)
CAMS_START = "2022-08-01"  # first day Open-Meteo serves CAMS for
WEATHER = ["temperature_2m", "relative_humidity_2m", "precipitation", "wind_speed_10m",
           "wind_direction_10m", "pressure_msl", "boundary_layer_height"]


def _url(url: str, tries: int = 4) -> bytes:
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return r.read()
        except OSError:  # timeouts and dropped connections on a few of the ~40k small downloads
            if attempt == tries - 1:
                raise
            time.sleep(2 ** attempt)


# ---------- station readings ----------

def _keys(location: int) -> list[str]:
    keys, token = [], None
    while True:
        q = {"list-type": 2, "prefix": f"records/csv.gz/locationid={location}/"} | ({"continuation-token": token} if token else {})
        xml = _url(f"{ARCHIVE}/?{urllib.parse.urlencode(q)}").decode()
        keys += re.findall(r"<Key>(.*?)</Key>", xml)
        token = (re.findall(r"<NextContinuationToken>(.*?)</NextContinuationToken>", xml) or [None])[0]
        if not token:
            return keys


def _readings(key: str) -> list[tuple]:
    text = gzip.decompress(_url(f"{ARCHIVE}/{key}")).decode()
    return [(r["datetime"], r["parameter"], r["value"]) for r in csv.DictReader(io.StringIO(text)) if r["parameter"] in ("pm25", "pm10")]


def station_readings(location: int) -> pd.DataFrame:
    """Raw 15-minute PM readings for one station, cached in data/raw and topped up on later runs."""
    cache = RAW / f"{location}.csv.gz"
    old = pd.read_csv(cache) if cache.exists() else pd.DataFrame(columns=["datetime", "parameter", "value"])
    last = old["datetime"].str[:10].max() if len(old) else "0000"
    all_keys = _keys(location)
    _save_coords(location, all_keys)
    keys = [k for k in all_keys if k[-15:-7] >= last.replace("-", "")]  # ...-YYYYMMDD.csv.gz
    with ThreadPoolExecutor(32) as ex:
        new = pd.DataFrame([row for rows in ex.map(_readings, keys) for row in rows], columns=["datetime", "parameter", "value"])
    df = pd.concat([old, new]).drop_duplicates(["datetime", "parameter"], keep="last").sort_values("datetime")
    RAW.mkdir(parents=True, exist_ok=True)
    df.to_csv(cache, index=False)
    return df


def _save_coords(location: int, keys: list[str]) -> None:
    coords = json.loads(COORDS.read_text()) if COORDS.exists() else {}
    if str(location) in coords or not keys:
        return
    row = next(csv.DictReader(io.StringIO(gzip.decompress(_url(f"{ARCHIVE}/{keys[-1]}")).decode())))
    coords[str(location)] = [float(row["lat"]), float(row["lon"])]
    RAW.mkdir(parents=True, exist_ok=True)
    COORDS.write_text(json.dumps(coords))


def clean_hourly(raw: pd.DataFrame) -> pd.DataFrame:
    """15-minute readings -> hourly PM2.5/PM10 after the quality checks described in the README."""
    df = raw.copy()
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["datetime"] = pd.to_datetime(df["datetime"].str[:19])  # local time already (+05:30)
    df = df[(df["value"] > 0) & (df["value"] < 985)]  # 985/999 are instrument error codes
    wide = df.pivot_table(index="datetime", columns="parameter", values="value")
    for p in ("pm25", "pm10"):
        if p not in wide:
            wide[p] = np.nan
        s = wide[p]
        stuck = s.groupby((s != s.shift()).cumsum()).transform("size") >= 8  # same value for 2+ hours
        wide.loc[stuck, p] = np.nan
    wide.loc[wide["pm25"] > wide["pm10"], ["pm25", "pm10"]] = np.nan  # PM2.5 is a subset of PM10
    hourly = wide[["pm25", "pm10"]].resample("h").mean()
    return hourly


def station_daily(hourly: pd.DataFrame) -> pd.DataFrame:
    """CPCB 24-hour averages (need 16 valid hours) and the station's PM-based AQI."""
    g = hourly.resample("D")
    d = g.mean().where(g.count() >= 16)
    d["aqi"] = np.fmax(d["pm25"].map(lambda c: sub_index("pm2_5", c)), d["pm10"].map(lambda c: sub_index("pm10", c)))
    return d


def hourly_profile(hourly: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Average PM by month and hour of day across a city's stations, as an hourly AQI-equivalent.

    CPCB's AQI is a 24-hour measure; this only shows when in the day the air is usually cleaner or dirtier.
    """
    h = pd.concat(hourly.values())
    h = h[h.index >= "2025-01-01"]  # the dense years; older data is too patchy to average by hour
    g = h.groupby([h.index.month.rename("month"), h.index.hour.rename("hour")])[["pm25", "pm10"]].mean().reset_index()
    g["aqi"] = np.fmax(g["pm25"].map(lambda c: sub_index("pm2_5", c)), g["pm10"].map(lambda c: sub_index("pm10", c)))
    return g


def city_air(city: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """City value = mean over the stations that reported that day (CPCB's city AQI is the station average).

    Also returns every station-day with the station's position, for the map, and the city's hourly profile.
    """
    names = {}
    for loc, name in STATIONS[city].items():
        names.setdefault(name, []).append(station_readings(loc))
    hourly = {name: clean_hourly(pd.concat(raws).drop_duplicates(["datetime", "parameter"])) for name, raws in names.items()}
    days = {name: station_daily(h) for name, h in hourly.items()}
    stacked = pd.concat(days, names=["station", "date"])
    g = stacked.groupby("date")
    out = g[["pm25", "pm10", "aqi"]].mean()
    out["stations"] = g["aqi"].count()

    coords = json.loads(COORDS.read_text())
    where = {name: coords[str(loc)] for loc, name in STATIONS[city].items() if str(loc) in coords}  # newest id wins
    st = stacked.dropna(subset=["aqi"]).reset_index()
    st.insert(0, "city", city)
    st["lat"], st["lon"] = st["station"].map(lambda n: where[n][0]), st["station"].map(lambda n: where[n][1])
    return out[out["stations"] >= 2], st, hourly_profile(hourly).assign(city=city)


# ---------- weather ----------

def weather_hourly(city: str, start: str | None = None, end: str | None = None, past_days: int | None = None) -> pd.DataFrame:
    """ERA5 history for a date range, or (past_days set) recent days plus the next two days' forecast."""
    lat, lon = CITIES[city]
    q = {"latitude": lat, "longitude": lon, "hourly": ",".join(WEATHER), "timezone": TZ}
    if past_days is None:
        url, q = WX_HISTORY, q | {"start_date": start, "end_date": end}
    else:
        url, q = WX_FORECAST, q | {"past_days": past_days, "forecast_days": 7}
    h = pd.DataFrame(json.loads(_url(f"{url}?{urllib.parse.urlencode(q)}"))["hourly"])
    h["time"] = pd.to_datetime(h["time"])
    return h.set_index("time")


def city_weather(city: str) -> pd.DataFrame:
    """ERA5 history; the forecast model fills the days ERA5 has not reached yet and the week ahead."""
    history = weather_hourly(city, START, str(date.today()))
    return history.combine_first(weather_hourly(city, past_days=10))


def cams_daily(city: str, end: str) -> pd.DataFrame:
    """Daily mean PM2.5/PM10 from Copernicus CAMS: its analysis for the past, its forecast for the next four days.

    CAMS reads low in Indian cities, but it rises and falls with the stations, which is what the model needs.
    """
    lat, lon = CITIES[city]
    q = {"latitude": lat, "longitude": lon, "hourly": "pm2_5,pm10", "timezone": TZ, "start_date": CAMS_START, "end_date": end}
    h = pd.DataFrame(json.loads(_url(f"{CAMS_API}?{urllib.parse.urlencode(q)}"))["hourly"])
    h["time"] = pd.to_datetime(h["time"])
    g = h.set_index("time").resample("D")
    return pd.DataFrame({"cams_pm25": g["pm2_5"].mean(), "cams_pm10": g["pm10"].mean()}).where(g["pm2_5"].count() >= 18)


def weather_daily(h: pd.DataFrame) -> pd.DataFrame:
    rad = np.deg2rad(h["wind_direction_10m"])
    h = h.assign(wind_u=-h["wind_speed_10m"] * np.sin(rad), wind_v=-h["wind_speed_10m"] * np.cos(rad))  # blowing towards E / N
    g = h.resample("D")
    return pd.DataFrame({
        "temp": g["temperature_2m"].mean(), "humidity": g["relative_humidity_2m"].mean(),
        "rain": g["precipitation"].sum(min_count=18), "wind": g["wind_speed_10m"].mean(),
        "wind_u": g["wind_u"].mean(), "wind_v": g["wind_v"].mean(), "pressure": g["pressure_msl"].mean(),
        "blh": g["boundary_layer_height"].mean(),
    })


def weather_vintage(city: str, end: str) -> pd.DataFrame:
    """Daily weather as it was FORECAST k = 1..7 days before each day, from Open-Meteo's archive of issued runs.

    Column `temp_lead3` on day T is the daily mean of the forecast hours for T, each taken from the run issued three
    days (72 hours) before that hour. These are the inputs a forecaster actually had, unlike ERA5, which is only
    known afterwards. Boundary-layer height is not archived, and CAMS has no such archive at all.
    """
    lat, lon = CITIES[city]
    out = []
    for k in LEADS:
        names = {w: f"{w}_previous_day{k}" for w in WEATHER if w != "boundary_layer_height"}
        q = {"latitude": lat, "longitude": lon, "timezone": TZ, "start_date": VINTAGE_START, "end_date": end,
             "hourly": ",".join(names.values())}
        h = pd.DataFrame(json.loads(_url(f"{WX_PREVIOUS}?{urllib.parse.urlencode(q)}"))["hourly"])
        h = h.rename(columns={v: w for w, v in names.items()}).assign(boundary_layer_height=np.nan)
        h["time"] = pd.to_datetime(h["time"])
        h = h.set_index("time")
        daily = weather_daily(h).drop(columns="blh").where(h["temperature_2m"].resample("D").count() >= 18)  # whole days only
        out.append(daily.add_suffix(f"_lead{k}"))
    return pd.concat(out, axis=1)


def build_vintage() -> pd.DataFrame:
    end = str(date.today() - timedelta(days=1))
    out = pd.concat([weather_vintage(city, end).assign(city=city) for city in CITIES]).rename_axis("date").reset_index()
    return out[["date", "city", *[c for c in out.columns if c not in ("date", "city")]]]


def load_vintage() -> pd.DataFrame | None:
    return pd.read_csv(VINTAGE_CSV, parse_dates=["date"]) if VINTAGE_CSV.exists() else None


def build() -> tuple[pd.DataFrame, pd.DataFrame]:
    """One row per city-day from START to six days ahead (future rows carry the weather forecast only)."""
    end = str(date.today() + timedelta(days=6))
    frames, stations, profiles = [], [], []
    for city in CITIES:
        air, st, profile = city_air(city)
        profiles.append(profile)
        cams_end = str(date.today() + timedelta(days=4))  # as far as the CAMS forecast reaches
        d = weather_daily(city_weather(city)).join(cams_daily(city, cams_end)).join(air, how="left").loc[START:end]  # keep weather-only days: lags must see the gaps
        d.insert(0, "city", city)
        frames.append(d)
        stations.append(st)
    out = pd.concat(frames)
    out.index.name = "date"
    return out.reset_index(), pd.concat(stations), pd.concat(profiles)


def save(daily: pd.DataFrame, stations: pd.DataFrame, profile: pd.DataFrame) -> None:
    daily.to_csv(DAILY_CSV, index=False, float_format="%.2f")
    stations[["city", "station", "date", "lat", "lon", "pm25", "pm10", "aqi"]].to_csv(STATIONS_CSV, index=False, float_format="%.2f")
    profile[["city", "month", "hour", "pm25", "pm10", "aqi"]].to_csv(HOURLY_CSV, index=False, float_format="%.2f")


def load() -> pd.DataFrame:
    return pd.read_csv(DAILY_CSV, parse_dates=["date"])


def load_stations() -> pd.DataFrame:
    return pd.read_csv(STATIONS_CSV, parse_dates=["date"])


def load_hourly() -> pd.DataFrame:
    return pd.read_csv(HOURLY_CSV)


if __name__ == "__main__":
    import sys
    if "--vintage" in sys.argv:  # only the archive of issued weather forecasts, for the forecast-vintage evaluation
        v = build_vintage()
        v.to_csv(VINTAGE_CSV, index=False, float_format="%.2f")
        print(f"{v.dropna(subset=['temp_lead1']).shape[0]} city-days of archived forecasts -> {VINTAGE_CSV}")
        sys.exit()
    df, st, profile = build()
    save(df, st, profile)
    ok = df.dropna(subset=["aqi"])
    print(f"{len(ok)} city-days with AQI ({df['date'].min():%Y-%m-%d} to {df['date'].max():%Y-%m-%d}) -> {DAILY_CSV}")
    print(ok.groupby("city")[["aqi", "pm25", "pm10", "stations"]].describe().T.round(1))
