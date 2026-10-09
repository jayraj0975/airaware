"""SQLite storage for accounts, saved places, alerts, notifications, citizen reports, the forecast log and the audit trail.

One file (AIRAWARE_DB, default data/airaware.db), WAL mode so readers never block the writer. Each call opens its own
short-lived connection, which keeps the code thread-safe without a pool.
"""

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAULT = Path(__file__).resolve().parents[2] / "data" / "airaware.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name TEXT NOT NULL,
    pw_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin')),
    city TEXT NOT NULL DEFAULT 'Pune',
    health TEXT NOT NULL DEFAULT '',          -- comma-separated health groups, see aqi.HEALTH_GROUPS
    email_alerts INTEGER NOT NULL DEFAULT 0,
    disabled INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    last_login TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,              -- sha256 of the cookie value; the raw token is never stored
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    ip TEXT, user_agent TEXT
);
CREATE TABLE IF NOT EXISTS places (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL, lat REAL NOT NULL, lon REAL NOT NULL, city TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    place_id INTEGER NOT NULL REFERENCES places(id) ON DELETE CASCADE,
    threshold INTEGER NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    last_sent TEXT,                           -- target date of the last warning, so each day warns once
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL, body TEXT NOT NULL,
    created_at TEXT NOT NULL,
    read INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    lat REAL NOT NULL, lon REAL NOT NULL, city TEXT NOT NULL,
    kind TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
    created_at TEXT NOT NULL,
    moderated_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    moderated_at TEXT
);
CREATE TABLE IF NOT EXISTS forecast_log (
    city TEXT NOT NULL, made_from TEXT NOT NULL, target TEXT NOT NULL,
    days_ahead INTEGER NOT NULL, forecast REAL NOT NULL, lo REAL NOT NULL, hi REAL NOT NULL,
    persistence REAL NOT NULL,                -- the last reading, the baseline every forecast must beat
    logged_at TEXT NOT NULL,
    actual REAL,                              -- filled in once the target day has been measured
    PRIMARY KEY (city, made_from, target)
);
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT,
    ok INTEGER, message TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY,
    at TEXT NOT NULL, user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    action TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '', ip TEXT
);
CREATE TABLE IF NOT EXISTS throttle (       -- attempts counted for rate limits (see take())
    action TEXT NOT NULL, key TEXT NOT NULL, at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS throttle_key ON throttle(action, key, at);
CREATE INDEX IF NOT EXISTS places_user ON places(user_id);
CREATE INDEX IF NOT EXISTS alerts_user ON alerts(user_id);
CREATE INDEX IF NOT EXISTS notes_user ON notifications(user_id, read);
CREATE INDEX IF NOT EXISTS reports_status ON reports(status, city, created_at);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS audit_action ON audit(action, at);
"""


def path() -> Path:
    return Path(os.environ.get("AIRAWARE_DB", DEFAULT))


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect():
    con = sqlite3.connect(path(), timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init() -> None:
    path().parent.mkdir(parents=True, exist_ok=True)
    with connect() as con:
        con.execute("PRAGMA journal_mode = WAL")
        con.executescript(SCHEMA)


def rows(sql: str, args=()) -> list[dict]:
    with connect() as con:
        return [dict(r) for r in con.execute(sql, args)]


def one(sql: str, args=()) -> dict | None:
    with connect() as con:
        r = con.execute(sql, args).fetchone()
        return dict(r) if r else None


def run(sql: str, args=()) -> int:
    """Executes a write; returns the new row id for an INSERT, else the number of rows changed."""
    with connect() as con:
        cur = con.execute(sql, args)
        return cur.lastrowid if sql.lstrip().upper().startswith("INSERT") else cur.rowcount


def take(action: str, key: str, limit: int, minutes: int) -> bool:
    """Records one attempt and returns True, or returns False if `limit` attempts were already made in the window.

    The count and the insert run in one IMMEDIATE transaction, which takes SQLite's write lock first, so requests
    arriving at the same moment are counted one after another and cannot all slip under the limit.
    """
    since = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat(timespec="seconds")
    con = sqlite3.connect(path(), timeout=10, isolation_level=None)
    try:
        con.execute("BEGIN IMMEDIATE")
        n = con.execute("SELECT COUNT(*) FROM throttle WHERE action = ? AND key = ? AND at >= ?", (action, key, since)).fetchone()[0]
        if n >= limit:
            con.execute("ROLLBACK")
            return False
        con.execute("INSERT INTO throttle (action, key, at) VALUES (?, ?, ?)", (action, key, now()))
        if n == 0:  # a key's first attempt in a window is a cheap moment to drop expired rows
            con.execute("DELETE FROM throttle WHERE at < ?", (since,))
        con.execute("COMMIT")
        return True
    except BaseException:
        if con.in_transaction:
            con.execute("ROLLBACK")
        raise
    finally:
        con.close()


def audit(action: str, user_id: int | None = None, detail: str = "", ip: str | None = None) -> None:
    run("INSERT INTO audit (at, user_id, action, detail, ip) VALUES (?, ?, ?, ?, ?)", (now(), user_id, action, detail[:500], ip))
