"""The live state behind the API, and the background jobs that keep it fresh.

`State` holds the data tables, the trained models and the current forecasts, swapped in whole after each refresh so a
request never sees half an update. The background loop rebuilds from the archive every AIRAWARE_REBUILD_HOURS, pulls
live readings hourly when OPENAQ_API_KEY is set, logs every forecast it issues and scores the logged ones once the
real AQI arrives, and raises users' alerts.
"""

import logging
import os
import smtplib
import threading
import time
from datetime import date
from email.message import EmailMessage

import pandas as pd

from airaware import live
from airaware.aqi import category, personal_advice
from airaware.data import STATIONS, build, load, load_hourly, load_stations, save
from airaware.model import forecast_now, train
from airaware.server import db

log = logging.getLogger("airaware")
REBUILD_HOURS = float(os.environ.get("AIRAWARE_REBUILD_HOURS", 6))
LIVE_MINUTES = 60


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


class State:
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
        self.after_forecast()

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
        self.after_forecast()

    def after_forecast(self):
        log_forecasts(self.forecast, self.forecast_daily)
        score_forecasts(self.forecast_daily)
        check_alerts(self)

    # ---- reads used by the API ----

    def latest_stations(self, city: str) -> tuple[pd.DataFrame, str]:
        """Each station's newest reading: live when available, else its last archive day within a week of the city's."""
        if not self.live.empty:
            lv = self.live.merge(self.stations.drop_duplicates("station")[["station", "city"]], on="station")
            lv = lv[lv["city"] == city]
            if len(lv) >= 2:
                return lv.assign(date=lv["last"].str[:16]), "live"
        s = self.stations[self.stations["city"] == city]
        s = s[s["date"] > s["date"].max() - pd.Timedelta(days=7)].sort_values("date").drop_duplicates("station", keep="last")
        return s, "archive"

    def area(self, lat: float, lon: float) -> dict | None:
        """Estimated AQI at a point and its forecast: the city forecast shifted by how the point compares with the
        city's stations on their latest day. None outside the covered cities."""
        city, km = live.nearest_city(lat, lon)
        if km > 60:
            return None
        with self.lock:
            s, source = self.latest_stations(city)
            fc = self.forecast[self.forecast["city"] == city]
        est = live.idw(s, lat, lon)
        offset = est["aqi"] - float(s["aqi"].mean())
        area_fc = fc.assign(forecast=(fc["forecast"] + offset).clip(lower=0), lo=(fc["lo"] + offset).clip(lower=0), hi=fc["hi"] + offset)
        return {"city": city, "source": source, "estimate": est, "offset": offset, "forecast": area_fc}


def upcoming(fc: pd.DataFrame) -> pd.DataFrame:
    """Forecast rows from today on (or the last one, if the forecast does not reach today)."""
    u = fc[fc["date"] >= pd.Timestamp(date.today())]
    return u if not u.empty else fc.tail(1)


# ---------- forecast log: every forecast issued, scored once the real AQI is known ----------

def log_forecasts(forecast: pd.DataFrame, daily: pd.DataFrame) -> None:
    last = daily.dropna(subset=["aqi"]).set_index(["city", "date"])["aqi"]
    with db.connect() as con:
        con.executemany(
            """INSERT OR IGNORE INTO forecast_log (city, made_from, target, days_ahead, forecast, lo, hi, persistence, logged_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [(r.city, r.made_from.date().isoformat(), r.date.date().isoformat(), int(r.days_ahead), float(r.forecast),
              float(r.lo), float(r.hi), float(last[(r.city, r.made_from)]), db.now()) for r in forecast.itertuples()])


def score_forecasts(daily: pd.DataFrame) -> int:
    actual = daily.dropna(subset=["aqi"])
    pending = db.rows("SELECT DISTINCT city, target FROM forecast_log WHERE actual IS NULL")
    known = {(c, d.date().isoformat()): a for c, d, a in zip(actual["city"], actual["date"], actual["aqi"])}
    done = 0
    with db.connect() as con:
        for p in pending:
            a = known.get((p["city"], p["target"]))
            if a is not None:
                done += con.execute("UPDATE forecast_log SET actual = ? WHERE city = ? AND target = ?", (float(a), p["city"], p["target"])).rowcount
    return done


# ---------- alerts ----------

def check_alerts(state: State, alert_id: int | None = None) -> int:
    """Warn each user once per target day when a saved place is forecast to reach their threshold today or tomorrow.

    The background jobs check every alert; a request that creates an alert checks only that one.
    """
    sent = 0
    only = "AND a.id = ?" if alert_id is not None else ""
    for a in db.rows(f"""SELECT a.*, p.name AS place, p.lat, p.lon, u.email, u.name AS user_name, u.health, u.email_alerts
                         FROM alerts a JOIN places p ON p.id = a.place_id JOIN users u ON u.id = a.user_id
                         WHERE a.active = 1 AND u.disabled = 0 {only}""", (alert_id,) if alert_id is not None else ()):
        area = state.area(a["lat"], a["lon"])
        if area is None:
            continue
        soon = upcoming(area["forecast"]).head(2)
        hit = soon[soon["forecast"] >= a["threshold"]]
        if hit.empty:
            continue
        r = hit.iloc[0]
        target = r["date"].date().isoformat()
        if a["last_sent"] and a["last_sent"] >= target:
            continue
        name = category(r["forecast"])[0]
        advice = personal_advice(r["forecast"], a["health"].split(","))["text"]
        when = "today" if r["date"] == pd.Timestamp(date.today()) else f"on {r['date']:%A %d %B}"
        title = f"{a['place']}: AQI {r['forecast']:.0f} ({name}) expected {when}"
        body = f"Your alert is set at {a['threshold']}. Likely range {r['lo']:.0f}–{r['hi']:.0f}. {advice}"
        db.run("INSERT INTO notifications (user_id, title, body, created_at) VALUES (?, ?, ?, ?)", (a["user_id"], title, body, db.now()))
        db.run("UPDATE alerts SET last_sent = ? WHERE id = ?", (target, a["id"]))
        if a["email_alerts"]:
            send_email(a["email"], title, f"Hi {a['user_name']},\n\n{title}.\n{body}\n\n— AirAware")
        sent += 1
    return sent


def send_email(to: str, subject: str, text: str) -> bool:
    """Sends through AIRAWARE_SMTP_HOST when configured; otherwise the in-app notification is the only channel."""
    host = os.environ.get("AIRAWARE_SMTP_HOST")
    if not host:
        return False
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = os.environ.get("AIRAWARE_SMTP_FROM", "alerts@airaware.local"), to, subject
    msg.set_content(text)
    try:
        with smtplib.SMTP(host, int(os.environ.get("AIRAWARE_SMTP_PORT", 587)), timeout=15) as s:
            s.starttls()
            if os.environ.get("AIRAWARE_SMTP_USER"):
                s.login(os.environ["AIRAWARE_SMTP_USER"], os.environ["AIRAWARE_SMTP_PASSWORD"])
            s.send_message(msg)
        return True
    except (OSError, smtplib.SMTPException) as e:
        log.warning("email to %s failed: %s", to, e)
        return False


# ---------- background jobs ----------

_job_lock = threading.Lock()


def run_job(kind: str, fn) -> bool:
    """Runs one job at a time and records it in the jobs table for the admin page."""
    if not _job_lock.acquire(blocking=False):
        return False
    job = db.run("INSERT INTO jobs (kind, started_at) VALUES (?, ?)", (kind, db.now()))
    try:
        msg = fn() or ""
        db.run("UPDATE jobs SET finished_at = ?, ok = 1, message = ? WHERE id = ?", (db.now(), str(msg)[:500], job))
        return True
    except Exception as e:  # a failed refresh must never take the site down; the admin page shows the error
        log.exception("job %s failed", kind)
        db.run("UPDATE jobs SET finished_at = ?, ok = 0, message = ? WHERE id = ?", (db.now(), f"{type(e).__name__}: {e}"[:500], job))
        return False
    finally:
        _job_lock.release()


def rebuild(state: State) -> str:
    daily, stations, profile = build()
    save(daily, stations, profile)
    state.load()
    last = daily.dropna(subset=["aqi"])["date"].max()
    return f"{len(daily.dropna(subset=['aqi']))} city-days, latest reading {last:%d %b %Y}; models retrained"


def pull_live(state: State) -> str:
    readings = live.openaq_latest({loc: name for c in STATIONS.values() for loc, name in c.items()})
    if readings.empty:
        return "no live readings returned"
    state.set_live(readings)
    return f"{len(readings)} stations live"


def refresher(state: State):
    last_build = time.time()
    while True:
        time.sleep(LIVE_MINUTES * 60)
        if os.environ.get("OPENAQ_API_KEY"):
            run_job("live readings", lambda: pull_live(state))
        if time.time() - last_build >= REBUILD_HOURS * 3600:
            run_job("scheduled rebuild", lambda: rebuild(state))
            last_build = time.time()
