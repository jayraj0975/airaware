"""Passwords, sessions and access control.

- Passwords: scrypt (memory-hard, in the standard library) with a random salt per user.
- Sessions: a random token in an HttpOnly, SameSite=Lax cookie; only its SHA-256 is stored, so a leaked database
  cannot be replayed as logins. Sessions last 30 days and are deleted on logout or password change.
- Cross-site requests: every state-changing API call must carry the X-AirAware header (see app.py). Browsers do not
  let another site add custom headers without a CORS preflight, which this API never grants.
- Brute force: at most 10 sign-in attempts per 15 minutes per email and 20 per IP (per /64 for IPv6), counted in the
  database with an atomic check-and-record, so parallel requests cannot slip past.
- Admins are made only from the server's command line (manage.py), never by signing up with a particular email:
  the site does not verify email ownership, so an email list would let anyone claim admin.
"""

import base64
import hashlib
import hmac
import struct
import time
import os
import re
import secrets
import ipaddress
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request, Response

from airaware.server import db

COOKIE = "aa_session"
SESSION_DAYS = 30
EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[a-z]{2,}$", re.I)
MIN_PASSWORD = 8


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt$16384$8$1${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, digest = stored.split("$")
        got = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=32)
    except ValueError:
        return False
    return hmac.compare_digest(got.hex(), digest)


def check_new_password(password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise HTTPException(422, f"Use at least {MIN_PASSWORD} characters for the password.")
    if len(password) > 256:
        raise HTTPException(422, "That password is too long.")


def check_email(email: str) -> str:
    email = email.strip()
    if not EMAIL.match(email):
        raise HTTPException(422, "That does not look like an email address.")
    return email


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def start_session(response: Response, user_id: int, request: Request) -> None:
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)
    db.run("INSERT INTO sessions (token_hash, user_id, created_at, expires_at, ip, user_agent) VALUES (?, ?, ?, ?, ?, ?)",
           (_hash(token), user_id, db.now(), expires.isoformat(timespec="seconds"), client_ip(request),
            request.headers.get("user-agent", "")[:200]))
    db.run("UPDATE users SET last_login = ? WHERE id = ?", (db.now(), user_id))
    response.set_cookie(COOKIE, token, max_age=SESSION_DAYS * 86400, httponly=True, samesite="lax",
                        secure=os.environ.get("AIRAWARE_SECURE_COOKIES") == "1", path="/")


def end_session(request: Request, response: Response) -> None:
    token = request.cookies.get(COOKIE)
    if token:
        db.run("DELETE FROM sessions WHERE token_hash = ?", (_hash(token),))
    response.delete_cookie(COOKIE, path="/")


def end_all_sessions(user_id: int) -> None:
    """Signs the user out everywhere and voids any reset link still outstanding: called whenever the password
    changes or the account is disabled, so no older credential survives."""
    db.run("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    db.run("UPDATE password_resets SET used_at = ? WHERE user_id = ? AND used_at IS NULL", (db.now(), user_id))


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "?"


def current_user(request: Request) -> dict | None:
    token = request.cookies.get(COOKIE)
    if not token:
        return None
    u = db.one("""SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id
                  WHERE s.token_hash = ? AND s.expires_at > ? AND u.disabled = 0""", (_hash(token), db.now()))
    return u


def require_user(user: dict | None = Depends(current_user)) -> dict:
    if not user:
        raise HTTPException(401, "Sign in first.")
    return user


def require_admin(user: dict = Depends(require_user)) -> dict:
    if user["role"] != "admin":
        raise HTTPException(403, "Admins only.")
    if admin_needs_two_step() and not user.get("totp_enabled_at"):
        raise HTTPException(403, "Turn on two-step sign-in on your dashboard to use the admin console.")
    return user


POLICY_VERSION = "2026-10-10"  # bump when the Terms or Privacy Notice change; users are asked to agree again


def public_user(u: dict) -> dict:
    return {k: u[k] for k in ("id", "email", "name", "role", "city", "email_alerts", "created_at", "last_login")} | {
        "health": [h for h in u["health"].split(",") if h],
        "health_consent": bool(u.get("health_consent_at")),
        "needs_consent": u.get("terms_version") != POLICY_VERSION,
        "two_step": bool(u.get("totp_enabled_at"))}


LOGIN_LIMIT = 10
LOGIN_WINDOW_MINUTES = 15


def visitor(host: str) -> str:
    """The rate-limit key for an address. An IPv6 user usually controls a whole /64, so that is one visitor."""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return host
    return str(ipaddress.ip_network(f"{ip}/64", strict=False)) if ip.version == 6 else str(ip)


def allow_login(ip_key: str, email: str) -> bool:
    """At most LOGIN_LIMIT sign-in attempts per window against one email, and twice that from one visitor.

    Atomic check-and-record (see db.take), so parallel requests cannot slip past the limit.
    """
    return db.take("login.ip", ip_key, LOGIN_LIMIT * 2, LOGIN_WINDOW_MINUTES) and db.take("login.email", email, LOGIN_LIMIT, LOGIN_WINDOW_MINUTES)


def new_reset_token(user_id: int, hours: int, created_by: int | None = None) -> str:
    """A one-time password-reset token; only its hash is stored. Earlier unused tokens for the user stop working."""
    token = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat(timespec="seconds")
    db.run("UPDATE password_resets SET used_at = ? WHERE user_id = ? AND used_at IS NULL", (db.now(), user_id))
    db.run("INSERT INTO password_resets (token_hash, user_id, expires_at, created_by) VALUES (?, ?, ?, ?)",
           (_hash(token), user_id, expires, created_by))
    return token


def use_reset_token(token: str) -> int | None:
    """Marks a valid token used and returns its user id; None if it is unknown, used or expired. The UPDATE is the
    check, so two requests with the same token cannot both succeed."""
    with db.connect() as con:
        row = con.execute("""UPDATE password_resets SET used_at = ? WHERE token_hash = ? AND used_at IS NULL AND expires_at > ?
                             RETURNING user_id""", (db.now(), _hash(token), db.now())).fetchone()
    return row["user_id"] if row else None


# ---------- two-step sign-in (TOTP, RFC 6238: 6 digits, 30-second steps, SHA-1, as authenticator apps expect) ----------

def new_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def totp_code(secret: str, step: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    return f"{(struct.unpack('>I', digest[offset:offset + 4])[0] & 0x7FFFFFFF) % 1_000_000:06d}"


def check_totp(user: dict, code: str) -> bool:
    """True if `code` is valid now (allowing one step of clock drift either way) and newer than the last code used.
    The last step is stored, so the same code cannot be used twice."""
    code = "".join(ch for ch in str(code) if ch.isdigit())
    if not user.get("totp_secret") or len(code) != 6:
        return False
    now = int(time.time() // 30)
    for step in (now - 1, now, now + 1):
        if step > (user.get("totp_last_step") or 0) and hmac.compare_digest(totp_code(user["totp_secret"], step), code):
            # Conditional update: two requests racing with the same code cannot both succeed.
            return db.run("UPDATE users SET totp_last_step = ? WHERE id = ? AND COALESCE(totp_last_step, 0) < ?",
                          (step, user["id"], step)) == 1
    return False


def admin_needs_two_step() -> bool:
    return os.environ.get("AIRAWARE_ADMIN_2FA", "1") == "1"
