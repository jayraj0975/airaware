"""Admin console API: platform overview, users, report moderation, data pipeline and jobs, audit trail."""

import threading

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from airaware.data import STATIONS
from airaware.insights import station_agreement
from airaware.model import AIRAWARE, PERSISTENCE
from airaware.server import db, reports
from airaware.server.auth import client_ip, end_all_sessions, new_reset_token, require_admin
from airaware.server.core import _job_lock, rebuild, run_job
from airaware.server.public import clean, records, state

router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin)])


class UserChange(BaseModel):
    role: str | None = None
    disabled: bool | None = None


class Moderation(BaseModel):
    status: str


@router.get("/overview")
def overview(request: Request):
    s = state(request)
    counts = db.one("""SELECT (SELECT COUNT(*) FROM users) AS users,
                              (SELECT COUNT(*) FROM users WHERE created_at >= date('now', '-7 days')) AS new_users,
                              (SELECT COUNT(*) FROM users WHERE last_login >= date('now', '-7 days')) AS active_users,
                              (SELECT COUNT(*) FROM places) AS places,
                              (SELECT COUNT(*) FROM alerts WHERE active = 1) AS alerts,
                              (SELECT COUNT(*) FROM notifications WHERE created_at >= date('now', '-7 days')) AS warnings_week,
                              (SELECT COUNT(*) FROM forecast_log) AS forecasts_logged,
                              (SELECT COUNT(*) FROM forecast_log WHERE actual IS NOT NULL) AS forecasts_scored,
                              (SELECT COUNT(*) FROM privacy_requests WHERE status = 'open') AS privacy_open""")
    signups = db.rows("""SELECT substr(created_at, 1, 10) AS day, COUNT(*) AS n FROM users
                         WHERE created_at >= date('now', '-30 days') GROUP BY day ORDER BY day""")
    with s.lock:
        d, stations, r = s.daily, s.stations, s.result
        trained, live_at, live_n = s.trained_at, s.live_at, len(s.live)
    measured = d.dropna(subset=["aqi"])
    freshness = []
    for city, g in measured.groupby("city"):
        last = g["date"].max()
        st = stations[(stations["city"] == city) & (stations["date"] > last - pd.Timedelta(days=7))]
        freshness.append({"city": city, "last_measured": last.date().isoformat(),
                          "days_behind": (pd.Timestamp.today().normalize() - last).days,
                          "stations_reporting": st["station"].nunique(), "stations_total": len(set(STATIONS[city].values())),
                          "weather_until": d[d["city"] == city].dropna(subset=["temp"])["date"].max().date().isoformat()})
    both = r.table[r.table["City"] == "Both"].set_index("Method")["MAE"]
    try:
        rc = reports.store().counts()
        counts |= {"reports_pending": rc["pending"], "reports": rc["total"]}
    except reports.Unavailable:
        counts |= {"reports_pending": None, "reports": None}
    return clean({"counts": counts, "reports_store": reports.describe(), "signups": signups, "freshness": freshness, "trained_at": trained,
                  "live": {"at": live_at, "stations": live_n},
                  "model": {"mae": both.get(AIRAWARE), "persistence_mae": both.get(PERSISTENCE),
                            "dm_p": r.dm[1], "test_forecasts": len(r.test)},
                  "job_running": _job_lock.locked()})


@router.get("/users")
def users(q: str = "", limit: int = Query(100, le=500)):
    like = f"%{q.strip()}%"
    rows = db.rows("""SELECT u.id, u.email, u.name, u.role, u.city, u.health, u.disabled, u.created_at, u.last_login,
                             (SELECT COUNT(*) FROM places p WHERE p.user_id = u.id) AS places,
                             (SELECT COUNT(*) FROM alerts a WHERE a.user_id = u.id) AS alerts
                      FROM users u WHERE u.email LIKE ? OR u.name LIKE ? ORDER BY u.id DESC LIMIT ?""", (like, like, limit))
    try:
        per_user = reports.store().per_user()
    except reports.Unavailable:
        per_user = None
    return [{**u, "reports": per_user.get(u["id"], 0) if per_user is not None else None} for u in rows]


@router.patch("/users/{uid}")
def change_user(uid: int, body: UserChange, request: Request, admin: dict = Depends(require_admin)):
    u = db.one("SELECT * FROM users WHERE id = ?", (uid,))
    if not u:
        raise HTTPException(404, "No such user.")
    if uid == admin["id"]:
        raise HTTPException(422, "You cannot change your own role or disable yourself.")
    if body.role is not None:
        if body.role not in ("user", "admin"):
            raise HTTPException(422, "role must be user or admin")
        db.run("UPDATE users SET role = ? WHERE id = ?", (body.role, uid))
        db.audit("admin.set_role", admin["id"], f"user {uid} ({u['email']}) -> {body.role}", client_ip(request))
    if body.disabled is not None:
        db.run("UPDATE users SET disabled = ? WHERE id = ?", (int(body.disabled), uid))
        if body.disabled:
            end_all_sessions(uid)
        db.audit("admin.disable" if body.disabled else "admin.enable", admin["id"], f"user {uid} ({u['email']})", client_ip(request))
    return {"ok": True}


@router.post("/users/{uid}/reset-link")
def reset_link(uid: int, request: Request, admin: dict = Depends(require_admin)):
    """A one-time reset link (valid 24 hours) for the admin to pass to the user, for when email is not set up."""
    u = db.one("SELECT id, email FROM users WHERE id = ?", (uid,))
    if not u:
        raise HTTPException(404, "No such user.")
    token = new_reset_token(uid, hours=24, created_by=admin["id"])
    db.audit("admin.reset_link", admin["id"], f"user {uid} ({u['email']})", client_ip(request))
    return {"path": f"/reset#token={token}", "expires_hours": 24}  # after "#": never sent to the server, so never in its logs


def _unavailable() -> HTTPException:
    return HTTPException(503, "The report database is offline, so reports cannot be listed or moderated right now.")


def _day(value: str | None, name: str) -> str | None:
    """A YYYY-MM-DD filter as the start of that day in UTC; anything else is refused."""
    if not value:
        return None
    try:
        return pd.Timestamp(value).tz_localize("UTC").isoformat()
    except (ValueError, TypeError):
        raise HTTPException(422, f"{name} must be a date like 2026-10-01.")


@router.get("/reports")
def list_reports(status: str | None = "pending", kind: str | None = None, city: str | None = None,
                 since: str | None = None, until: str | None = None, limit: int = Query(200, ge=1, le=500)):
    """Moderation queue and archive, filtered by status, kind, city and date (until is inclusive of that day)."""
    if status not in (None, "", "all", *reports.STATUSES):
        raise HTTPException(422, "status must be pending, approved, rejected or all")
    if kind and kind not in reports.KINDS:
        raise HTTPException(422, f"kind must be one of {', '.join(reports.KINDS)}")
    if city and city not in reports.CITIES:
        raise HTTPException(422, "city must be Pune or Mumbai")
    until_day = _day(until, "until")
    f = reports.Filter(status=None if status in (None, "", "all") else status, kind=kind or None, city=city or None,
                       since=_day(since, "since"), limit=limit,
                       until=(pd.Timestamp(until_day) + pd.Timedelta(days=1)).isoformat() if until_day else None)
    try:
        rs = reports.store().find(f)
    except reports.Unavailable:
        raise _unavailable()
    emails = {u["id"]: u["email"] for u in db.rows("SELECT id, email FROM users")} if rs else {}
    return [{**r, "author": emails.get(r["user_id"])} for r in rs]


@router.get("/reports/stats")
def report_stats(days: int = Query(90, ge=1, le=3650)):
    """Counts by status, by city and kind, the weekly trend and moderation turnaround (an aggregation in MongoDB)."""
    since = (pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=days)).isoformat(timespec="seconds")
    try:
        out = reports.store().stats(since)
    except reports.Unavailable:
        raise _unavailable()
    return clean({**out, "days": days, "backend": reports.store().backend,
                  "by_city_kind": [{**x, "label": reports.KINDS.get(x["kind"], x["kind"])} for x in out["by_city_kind"]]})


@router.patch("/reports/{rid}")
def moderate(rid: str, body: Moderation, request: Request, admin: dict = Depends(require_admin)):
    if body.status not in reports.STATUSES:
        raise HTTPException(422, "status must be approved, rejected or pending")
    try:
        if not reports.store().moderate(rid, body.status, admin["id"]):
            raise HTTPException(404, "No such report.")
    except reports.Unavailable:
        raise _unavailable()
    db.audit(f"admin.report_{body.status}", admin["id"], f"report {rid}", client_ip(request))
    return {"ok": True}


@router.delete("/reports/{rid}")
def delete_report(rid: str, request: Request, admin: dict = Depends(require_admin)):
    """Removes a report for good (spam, personal details in a note). Rejecting keeps it on record instead."""
    try:
        if not reports.store().delete(rid):
            raise HTTPException(404, "No such report.")
    except reports.Unavailable:
        raise _unavailable()
    db.audit("admin.report_deleted", admin["id"], f"report {rid}", client_ip(request))
    return {"ok": True}


@router.get("/stations")
def stations(request: Request):
    s = state(request)
    with s.lock:
        st = s.stations
    trust = station_agreement(st)
    last = st.sort_values("date").drop_duplicates("station", keep="last")[["station", "date", "aqi"]]
    days = st[st["date"] > st["date"].max() - pd.Timedelta(days=30)].groupby("station").size().rename("days_30")
    out = trust.merge(last, on="station", how="left").merge(days, on="station", how="left").fillna({"days_30": 0})
    return records(out.assign(date=out["date"].astype(str).str[:10]).sort_values(["city", "correlation"]))


@router.get("/jobs")
def jobs():
    return db.rows("SELECT * FROM jobs ORDER BY id DESC LIMIT 50")


@router.post("/refresh", status_code=202)
def refresh(request: Request, admin: dict = Depends(require_admin)):
    """Starts a full rebuild (download, clean, retrain) in the background; one at a time."""
    if _job_lock.locked():
        raise HTTPException(409, "A job is already running.")
    s = state(request)
    threading.Thread(target=run_job, args=("manual rebuild", lambda: rebuild(s)), daemon=True).start()
    db.audit("admin.refresh", admin["id"], "", client_ip(request))
    return {"started": True}


@router.post("/backup")
def backup_now(request: Request, admin: dict = Depends(require_admin)):
    """Makes a backup now and sends it. It holds every account (password hashes included), so it is audited."""
    f = db.backup()
    db.audit("admin.backup_download", admin["id"], f.name, client_ip(request))
    return FileResponse(f, media_type="application/x-sqlite3", filename=f.name)


class Resolution(BaseModel):
    response: str


@router.get("/privacy-requests")
def privacy_requests(status: str = "open"):
    return db.rows("SELECT * FROM privacy_requests WHERE status = ? ORDER BY id DESC LIMIT 200", (status,))


@router.patch("/privacy-requests/{rid}")
def resolve_privacy_request(rid: int, body: Resolution, request: Request, admin: dict = Depends(require_admin)):
    """Mark a request answered, recording what was done (reply to the person by email as well)."""
    if not body.response.strip():
        raise HTTPException(422, "Write what was done, for the record.")
    if not db.run("UPDATE privacy_requests SET status = 'resolved', response = ?, resolved_at = ?, resolved_by = ? WHERE id = ?",
                  (body.response.strip()[:2000], db.now(), admin["id"], rid)):
        raise HTTPException(404, "No such request.")
    db.audit("admin.privacy_resolved", admin["id"], f"request {rid}", client_ip(request))
    return {"ok": True}


@router.get("/audit")
def audit(limit: int = Query(200, le=1000)):
    return db.rows("""SELECT a.*, u.email FROM audit a LEFT JOIN users u ON u.id = a.user_id ORDER BY a.id DESC LIMIT ?""", (limit,))
