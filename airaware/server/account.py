"""Sign-up, sign-in and everything a signed-in user owns: profile, saved places, alerts and notifications."""

import os
import sqlite3
import urllib.parse

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
    accept_terms: bool = False   # agreed to the Terms and the Privacy Notice (DPDP Act: free, specific, informed consent)
    adult: bool = False          # 18 or older; the Act needs verifiable parental consent for children, which we do not take


class SignIn(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=256)
    code: str | None = Field(None, max_length=12)  # two-step sign-in code, when turned on


class TwoStep(BaseModel):
    code: str = Field(max_length=12)
    password: str | None = Field(None, max_length=256)


class Forgot(BaseModel):
    email: str = Field(max_length=320)


class Reset(BaseModel):
    token: str = Field(max_length=200)
    password: str = Field(max_length=256)


class Profile(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=80)
    city: str | None = None
    health: list[str] | None = Field(None, max_length=10)
    health_consent: bool | None = None  # must be true the first time health information is saved
    email_alerts: bool | None = None


class PrivacyRequest(BaseModel):
    email: str = Field(max_length=320)
    kind: str
    message: str = Field(min_length=5, max_length=2000)


class PasswordChange(BaseModel):
    current: str = Field(max_length=256)
    new: str = Field(max_length=256)


class Place(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    lat: float = Field(ge=-90, le=90, allow_inf_nan=False)  # Python's JSON parser accepts NaN; refuse it here
    lon: float = Field(ge=-180, le=180, allow_inf_nan=False)


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
    if not (body.accept_terms and body.adult):
        raise HTTPException(422, "To create an account, confirm you are 18 or older and agree to the Terms and the Privacy Notice.")
    ip = auth.visitor(client_ip(request))
    if not db.take("signup", ip, SIGNUPS_PER_HOUR, 60):
        raise HTTPException(429, "Too many new accounts from this network. Try again in an hour.")
    try:  # every sign-up is a plain user; admins are promoted from the server CLI (see auth.py)
        uid = db.run("""INSERT INTO users (email, name, pw_hash, city, created_at, terms_version, consent_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)""",
                     (email, body.name.strip(), auth.hash_password(body.password), body.city, db.now(), auth.POLICY_VERSION, db.now()))
    except sqlite3.IntegrityError:
        raise HTTPException(409, "An account with that email already exists. Sign in instead.")
    auth.start_session(response, uid, request)
    db.audit("user.signup", uid, email, ip)
    db.audit("consent.given", uid, f"terms and privacy notice {auth.POLICY_VERSION}; confirmed 18+", ip)
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
    if u["totp_enabled_at"]:
        if not body.code:
            raise HTTPException(401, "two_step_required")  # the password was right; the app now asks for the code
        if not auth.check_totp(u, body.code):
            db.audit("user.login_failed", u["id"], f"{email} (two-step code)", ip)
            raise HTTPException(401, "That code did not work. Check your authenticator app and try the newest code.")
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
        if body.health and not (user.get("health_consent_at") or body.health_consent):
            raise HTTPException(422, "Health information needs your explicit consent first.")
        fields["health"] = ",".join(sorted(set(body.health)))
        if body.health and not user.get("health_consent_at"):
            fields["health_consent_at"] = db.now()
            db.audit("consent.health_given", user["id"], "health information used to tailor advice and alerts")
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


class Reauth(BaseModel):
    password: str = Field(max_length=256)


@router.post("/me/2fa/setup")
def two_step_setup(body: Reauth, user: dict = Depends(require_user)):
    """Starts two-step sign-in: a new key for the authenticator app. It is not on until a code is confirmed.

    Needs the password: otherwise someone holding a stolen session could enrol their own authenticator and lock
    the owner out."""
    if user["totp_enabled_at"]:
        raise HTTPException(409, "Two-step sign-in is already on.")
    if not recheck_password(user, body.password):
        raise HTTPException(403, "Your password is not right.")
    secret = auth.new_totp_secret()
    db.run("UPDATE users SET totp_secret = ?, totp_last_step = NULL WHERE id = ?", (secret, user["id"]))
    label = urllib.parse.quote(f"AirAware:{user['email']}")
    return {"secret": secret, "uri": f"otpauth://totp/{label}?secret={secret}&issuer=AirAware&digits=6&period=30"}


@router.post("/me/2fa/enable")
def two_step_enable(body: TwoStep, request: Request, user: dict = Depends(require_user)):
    if not db.take("2fa", str(user["id"]), 10, 15):
        raise HTTPException(429, "Too many tries. Wait 15 minutes.")
    if user["totp_enabled_at"] or not auth.check_totp(user, body.code):
        raise HTTPException(400, "That code did not match. Use the newest code from your authenticator app.")
    db.run("UPDATE users SET totp_enabled_at = ? WHERE id = ?", (db.now(), user["id"]))
    db.audit("user.2fa_on", user["id"], "", client_ip(request))
    return auth.public_user(db.one("SELECT * FROM users WHERE id = ?", (user["id"],)))


@router.post("/me/2fa/disable")
def two_step_disable(body: TwoStep, request: Request, user: dict = Depends(require_user)):
    """Turning it off needs both the password and a current code."""
    if not user["totp_enabled_at"]:
        raise HTTPException(409, "Two-step sign-in is already off.")
    if not db.take("2fa", str(user["id"]), 10, 15):
        raise HTTPException(429, "Too many tries. Wait 15 minutes.")
    if not (body.password and recheck_password(user, body.password) and auth.check_totp(user, body.code)):
        raise HTTPException(403, "Password or code not right.")
    db.run("UPDATE users SET totp_secret = NULL, totp_enabled_at = NULL, totp_last_step = NULL WHERE id = ?", (user["id"],))
    db.audit("user.2fa_off", user["id"], "", client_ip(request))
    return auth.public_user(db.one("SELECT * FROM users WHERE id = ?", (user["id"],)))


@router.post("/me/consent")
def give_consent(request: Request, user: dict = Depends(require_user)):
    """Agree to the current Terms and Privacy Notice (asked again whenever they change)."""
    db.run("UPDATE users SET terms_version = ?, consent_at = ? WHERE id = ?", (auth.POLICY_VERSION, db.now(), user["id"]))
    db.audit("consent.given", user["id"], f"terms and privacy notice {auth.POLICY_VERSION}", client_ip(request))
    return auth.public_user(db.one("SELECT * FROM users WHERE id = ?", (user["id"],)))


@router.delete("/me/health")
def withdraw_health_consent(request: Request, user: dict = Depends(require_user)):
    """Withdraw consent for health information: it is erased at once and advice goes back to the general level."""
    db.run("UPDATE users SET health = '', health_consent_at = NULL WHERE id = ?", (user["id"],))
    db.audit("consent.health_withdrawn", user["id"], "health information erased", client_ip(request))
    return auth.public_user(db.one("SELECT * FROM users WHERE id = ?", (user["id"],)))


@router.get("/me/export")
def export_my_data(request: Request, user: dict = Depends(require_user)):
    """Everything AirAware holds about you, as JSON (DPDP Act section 11: a summary of your personal data and how it is used)."""
    if not db.take("export", str(user["id"]), 10, 60):
        raise HTTPException(429, "You have downloaded your data a lot in the last hour. Try again later.")
    uid = user["id"]
    profile = {k: v for k, v in user.items() if k not in ("pw_hash", "totp_secret", "totp_last_step")}
    db.audit("user.data_exported", uid, "", client_ip(request))
    return {
        "about": "Your personal data held by AirAware, and why. See /privacy for how each part is used and how long it is kept.",
        "exported_at": db.now(),
        "profile": profile | {"password": "stored only as a one-way scrypt hash; not included"},
        "purposes": {"email, name, password hash": "your account and signing in",
                     "city, places": "forecasts for the places you choose", "health groups": "tailoring advice and alert wording (only with your consent)",
                     "alerts, notifications": "warning you before bad air days", "reports": "showing pollution sources on the public map after moderation",
                     "sign-in records and IP addresses": "security: stopping password guessing and abuse"},
        "places": db.rows("SELECT id, name, lat, lon, city, created_at FROM places WHERE user_id = ?", (uid,)),
        "alerts": db.rows("SELECT id, place_id, threshold, active, last_sent, created_at FROM alerts WHERE user_id = ?", (uid,)),
        "notifications": db.rows("SELECT title, body, created_at, read FROM notifications WHERE user_id = ?", (uid,)),
        "reports": db.rows("SELECT id, lat, lon, city, kind, note, status, created_at FROM reports WHERE user_id = ?", (uid,)),
        "sessions": db.rows("SELECT created_at, expires_at, ip, user_agent FROM sessions WHERE user_id = ?", (uid,)),
        "privacy_requests": db.rows("SELECT kind, message, status, response, created_at, resolved_at FROM privacy_requests WHERE user_id = ?", (uid,)),
        "activity_log": db.rows("SELECT at, action, detail, ip FROM audit WHERE user_id = ? ORDER BY id DESC LIMIT 500", (uid,)),
    }


@router.post("/privacy/requests", status_code=201)
def privacy_request(body: PrivacyRequest, request: Request, user: dict | None = Depends(auth.current_user)):
    """Exercise a right under the DPDP Act or raise a grievance. Open to everyone, signed in or not."""
    kinds = {"access", "correction", "erasure", "withdraw", "grievance", "other"}
    if body.kind not in kinds:
        raise HTTPException(422, f"kind must be one of {', '.join(sorted(kinds))}")
    email = auth.check_email(body.email)
    if not db.take("privacy.ip", auth.visitor(client_ip(request)), 5, 60):
        raise HTTPException(429, "You have sent several requests in the last hour. We will answer those first.")
    rid = db.run("INSERT INTO privacy_requests (user_id, email, kind, message, created_at) VALUES (?, ?, ?, ?, ?)",
                 (user["id"] if user else None, email, body.kind, body.message.strip(), db.now()))
    db.audit("privacy.request", user["id"] if user else None, f"request {rid} ({body.kind})", client_ip(request))
    return {"id": rid, "detail": "Got it. We will reply to your email, within 30 days at the latest."}


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
