"""Sign-up, sign-in and everything a signed-in user owns: profile, saved places, alerts and notifications."""

import os
import sqlite3

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from airaware.aqi import HEALTH_GROUPS
from airaware.data import CITIES
from airaware.server import auth, db
from airaware.server.auth import client_ip, require_user
from airaware.server.core import check_alerts, send_email, upcoming
from airaware.server.public import forecast_rows, state

router = APIRouter(prefix="/api")
MAX_PLACES, MAX_ALERTS = 10, 20
SIGNUPS_PER_HOUR = 5  # per IPv4 address or IPv6 /64


class SignUp(BaseModel):
    email: str = Field(max_length=320)
    name: str = Field(min_length=1, max_length=80)
    password: str = Field(max_length=256)
    city: str = "Pune"


class SignIn(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=256)


class Forgot(BaseModel):
    email: str = Field(max_length=320)


class Reset(BaseModel):
    token: str = Field(max_length=200)
    password: str = Field(max_length=256)


class Profile(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=80)
    city: str | None = None
    health: list[str] | None = None
    email_alerts: bool | None = None


class PasswordChange(BaseModel):
    current: str = Field(max_length=256)
    new: str = Field(max_length=256)


class Place(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class Alert(BaseModel):
    place_id: int
    threshold: int = Field(ge=50, le=500)


class AlertChange(BaseModel):
    threshold: int | None = Field(None, ge=50, le=500)
    active: bool | None = None


# ---------- auth ----------

@router.post("/auth/signup", status_code=201)
def signup(body: SignUp, request: Request, response: Response):
    email = auth.check_email(body.email)
    auth.check_new_password(body.password)
    if body.city not in CITIES:
        raise HTTPException(422, "Pick Pune or Mumbai.")
    ip = auth.visitor(client_ip(request))
    if not db.take("signup", ip, SIGNUPS_PER_HOUR, 60):
        raise HTTPException(429, "Too many new accounts from this network. Try again in an hour.")
    try:  # every sign-up is a plain user; admins are promoted from the server CLI (see auth.py)
        uid = db.run("INSERT INTO users (email, name, pw_hash, city, created_at) VALUES (?, ?, ?, ?, ?)",
                     (email, body.name.strip(), auth.hash_password(body.password), body.city, db.now()))
    except sqlite3.IntegrityError:
        raise HTTPException(409, "An account with that email already exists. Sign in instead.")
    auth.start_session(response, uid, request)
    db.audit("user.signup", uid, email, ip)
    return auth.public_user(db.one("SELECT * FROM users WHERE id = ?", (uid,)))


@router.post("/auth/login")
def login(body: SignIn, request: Request, response: Response):
    ip, email = auth.visitor(client_ip(request)), body.email.strip().lower()
    if not auth.allow_login(ip, email):
        raise HTTPException(429, "Too many sign-in attempts. Wait 15 minutes and try again.")
    u = db.one("SELECT * FROM users WHERE email = ?", (email,))
    # Hash even when the email is unknown, so response time does not reveal which emails have accounts.
    ok = auth.verify_password(body.password, u["pw_hash"] if u else auth.hash_password("x"))
    if not u or not ok or u["disabled"]:
        db.audit("user.login_failed", u["id"] if u else None, email, ip)
        raise HTTPException(401, "Wrong email or password." if not (u and ok) else "This account is disabled.")
    auth.start_session(response, u["id"], request)
    db.audit("user.login", u["id"], email, ip)
    return auth.public_user(u)


@router.post("/auth/logout")
def logout(request: Request, response: Response):
    auth.end_session(request, response)
    return {"ok": True}


@router.post("/auth/forgot")
def forgot(body: Forgot, request: Request):
    """Emails a reset link if the account exists and email is set up. The answer is always the same, so it never
    reveals which emails have accounts. Links point at AIRAWARE_PUBLIC_URL, never at the request's Host header."""
    email = body.email.strip().lower()
    ip = auth.visitor(client_ip(request))
    sent_note = {"ok": True, "detail": "If that email has an account, a reset link is on its way. No email? Ask an admin for a reset link."}
    if not (db.take("forgot.ip", ip, 5, 60) and db.take("forgot.email", email, 3, 60)):
        return sent_note
    u = db.one("SELECT id, name, email FROM users WHERE email = ? AND disabled = 0", (email,))
    base = os.environ.get("AIRAWARE_PUBLIC_URL", "").rstrip("/")
    if u and base and os.environ.get("AIRAWARE_SMTP_HOST"):
        token = auth.new_reset_token(u["id"], hours=1)
        send_email(u["email"], "Reset your AirAware password",
                   f"Hi {u['name']},\n\nTo choose a new password, open this link within an hour:\n{base}/reset#token={token}\n\n"
                   "If you did not ask for this, ignore this email; your password has not changed.\n\n— AirAware")
        db.audit("user.reset_requested", u["id"], "", ip)
    return sent_note


@router.post("/auth/reset")
def reset(body: Reset, request: Request):
    auth.check_new_password(body.password)
    if not db.take("reset.ip", auth.visitor(client_ip(request)), 10, 60):
        raise HTTPException(429, "Too many attempts. Try again in an hour.")
    uid = auth.use_reset_token(body.token)
    if uid is None:
        raise HTTPException(400, "This reset link is invalid, already used or expired. Ask for a new one.")
    db.run("UPDATE users SET pw_hash = ? WHERE id = ?", (auth.hash_password(body.password), uid))
    auth.end_all_sessions(uid)
    db.audit("user.password_reset", uid, "", client_ip(request))
    return {"ok": True}


@router.get("/auth/me")
def me(user: dict | None = Depends(auth.current_user)):
    if not user:
        return {"user": None}
    unread = db.one("SELECT COUNT(*) AS n FROM notifications WHERE user_id = ? AND read = 0", (user["id"],))["n"]
    return {"user": auth.public_user(user), "unread": unread}


# ---------- profile ----------

@router.patch("/me")
def update_profile(body: Profile, user: dict = Depends(require_user)):
    fields = {}
    if body.name is not None:
        fields["name"] = body.name.strip()
    if body.city is not None:
        if body.city not in CITIES:
            raise HTTPException(422, "Pick Pune or Mumbai.")
        fields["city"] = body.city
    if body.health is not None:
        bad = set(body.health) - set(HEALTH_GROUPS)
        if bad:
            raise HTTPException(422, f"Unknown health group: {', '.join(sorted(bad))}")
        fields["health"] = ",".join(sorted(set(body.health)))
    if body.email_alerts is not None:
        fields["email_alerts"] = int(body.email_alerts)
    if fields:
        db.run(f"UPDATE users SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?", (*fields.values(), user["id"]))
    return auth.public_user(db.one("SELECT * FROM users WHERE id = ?", (user["id"],)))


def recheck_password(user: dict, password: str) -> bool:
    """Checks the password again for a sensitive change. Capped per account: each check costs a scrypt hash (on
    purpose slow and memory-hungry), so unlimited checks would let one signed-in session load the server or guess."""
    if not db.take("recheck", str(user["id"]), 5, 15):
        raise HTTPException(429, "Too many password checks. Wait 15 minutes and try again.")
    return auth.verify_password(password, user["pw_hash"])


@router.post("/me/password")
def change_password(body: PasswordChange, request: Request, response: Response, user: dict = Depends(require_user)):
    auth.check_new_password(body.new)
    if not recheck_password(user, body.current):
        raise HTTPException(403, "Your current password is not right.")
    db.run("UPDATE users SET pw_hash = ? WHERE id = ?", (auth.hash_password(body.new), user["id"]))
    auth.end_all_sessions(user["id"])  # sign out every other device
    auth.start_session(response, user["id"], request)
    db.audit("user.password_changed", user["id"], "", client_ip(request))
    return {"ok": True}


@router.delete("/me")
def delete_account(body: SignIn, request: Request, response: Response, user: dict = Depends(require_user)):
    """Deletes the account and everything it owns. Needs the password again; reports stay, without the author."""
    if body.email.strip().lower() != user["email"].lower() or not recheck_password(user, body.password):
        raise HTTPException(403, "Email or password is not right.")
    db.audit("user.deleted", None, f"user {user['id']} deleted their account", client_ip(request))
    db.run("DELETE FROM users WHERE id = ?", (user["id"],))
    response.delete_cookie(auth.COOKIE, path="/")
    return {"ok": True}


# ---------- places and the personal dashboard ----------

@router.get("/me/places")
def places(request: Request, user: dict = Depends(require_user)):
    """Each saved place with its forecast for today and the coming days, and advice for this user."""
    groups = [g for g in user["health"].split(",") if g]
    out = []
    for p in db.rows("SELECT * FROM places WHERE user_id = ? ORDER BY id", (user["id"],)):
        a = state(request).area(p["lat"], p["lon"])
        if a is None:
            out.append({**p, "forecast": []})
            continue
        rows = forecast_rows(upcoming(a["forecast"]), groups)
        out.append({**p, "estimate": a["estimate"]["aqi"], "forecast": rows,
                    "alerts": db.rows("SELECT id, threshold, active, last_sent FROM alerts WHERE place_id = ?", (p["id"],))})
    return out


@router.post("/me/places", status_code=201)
def add_place(body: Place, request: Request, user: dict = Depends(require_user)):
    a = state(request).area(body.lat, body.lon)
    if a is None:
        raise HTTPException(422, "AirAware covers the Pune and Mumbai areas.")
    if db.one("SELECT COUNT(*) AS n FROM places WHERE user_id = ?", (user["id"],))["n"] >= MAX_PLACES:
        raise HTTPException(422, f"You can save up to {MAX_PLACES} places.")
    pid = db.run("INSERT INTO places (user_id, name, lat, lon, city, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                 (user["id"], body.name.strip(), body.lat, body.lon, a["city"], db.now()))
    return {"id": pid}


@router.delete("/me/places/{pid}")
def delete_place(pid: int, user: dict = Depends(require_user)):
    if not db.run("DELETE FROM places WHERE id = ? AND user_id = ?", (pid, user["id"])):
        raise HTTPException(404, "No such place.")
    return {"ok": True}


# ---------- alerts and notifications ----------

@router.post("/me/alerts", status_code=201)
def add_alert(body: Alert, request: Request, user: dict = Depends(require_user)):
    if not db.one("SELECT id FROM places WHERE id = ? AND user_id = ?", (body.place_id, user["id"])):
        raise HTTPException(404, "No such place.")
    if db.one("SELECT COUNT(*) AS n FROM alerts WHERE user_id = ?", (user["id"],))["n"] >= MAX_ALERTS:
        raise HTTPException(422, f"You can have up to {MAX_ALERTS} alerts.")
    aid = db.run("INSERT INTO alerts (user_id, place_id, threshold, created_at) VALUES (?, ?, ?, ?)",
                 (user["id"], body.place_id, body.threshold, db.now()))
    check_alerts(state(request), alert_id=aid)  # only this alert, so a bad day already in the forecast warns now
    return {"id": aid}


@router.patch("/me/alerts/{aid}")
def change_alert(aid: int, body: AlertChange, user: dict = Depends(require_user)):
    a = db.one("SELECT * FROM alerts WHERE id = ? AND user_id = ?", (aid, user["id"]))
    if not a:
        raise HTTPException(404, "No such alert.")
    db.run("UPDATE alerts SET threshold = ?, active = ?, last_sent = CASE WHEN ? THEN NULL ELSE last_sent END WHERE id = ?",
           (body.threshold or a["threshold"], a["active"] if body.active is None else int(body.active),
            int(body.threshold is not None and body.threshold != a["threshold"]), aid))
    return {"ok": True}


@router.delete("/me/alerts/{aid}")
def delete_alert(aid: int, user: dict = Depends(require_user)):
    if not db.run("DELETE FROM alerts WHERE id = ? AND user_id = ?", (aid, user["id"])):
        raise HTTPException(404, "No such alert.")
    return {"ok": True}


@router.get("/me/notifications")
def notifications(user: dict = Depends(require_user)):
    return db.rows("SELECT id, title, body, created_at, read FROM notifications WHERE user_id = ? ORDER BY id DESC LIMIT 50", (user["id"],))


@router.post("/me/notifications/read")
def mark_read(user: dict = Depends(require_user)):
    db.run("UPDATE notifications SET read = 1 WHERE user_id = ?", (user["id"],))
    return {"ok": True}


@router.get("/me/reports")
def my_reports(user: dict = Depends(require_user)):
    return db.rows("SELECT id, lat, lon, city, kind, note, status, created_at FROM reports WHERE user_id = ? ORDER BY id DESC LIMIT 100", (user["id"],))
