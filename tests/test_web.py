"""Server tests on the committed data, with a throwaway database and the network calls stubbed out."""

import os
import tempfile

import pandas as pd
import pytest
from fastapi.testclient import TestClient

os.environ["AIRAWARE_REFRESH"] = "0"
os.environ["AIRAWARE_ADMIN_2FA"] = "0"  # admin tests below; test_two_step_sign_in checks enforcement
os.environ["AIRAWARE_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")

from airaware import live  # noqa: E402
from airaware.server import account, app as server, auth, core, db, manage, public  # noqa: E402

H = {"X-AirAware": "1"}
WEATHER = {"current": {"time": "2026-10-09T21:00", "temperature_2m": 27.0, "relative_humidity_2m": 50, "apparent_temperature": 28.0,
                       "precipitation": 0, "weather_code": 0, "wind_speed_10m": 4.0, "wind_direction_10m": 270, "surface_pressure": 950},
           "hourly": {"time": ["2026-10-09T21:00"], "temperature_2m": [27.0]}}


@pytest.fixture(scope="module")
def app():
    mp = pytest.MonkeyPatch()
    mp.setattr(live, "weather_now", lambda lat, lon: WEATHER)
    mp.setattr(live, "place_name", lambda lat, lon: "Test Nagar, Pune")
    mp.setattr(live, "search_places", lambda q, city: [{"name": "Kothrud", "area": "Pune", "lat": 18.507, "lon": 73.806}])
    mp.setattr(account, "SIGNUPS_PER_HOUR", 1000)  # every test client signs up from the same address
    with TestClient(server.app) as c:
        yield c
    mp.undo()


def client(app):
    """A fresh browser: its own cookie jar on the same app."""
    return TestClient(server.app)


def signup(c, email, name="Asha", password="correct horse", city="Pune"):
    return c.post("/api/auth/signup", json={"email": email, "name": name, "password": password, "city": city, "accept_terms": True, "adult": True}, headers=H)


def test_public_pages_and_api(app):
    status = app.get("/api/status").json()
    assert set(status["cities"]) == {"Pune", "Mumbai"} and status["live_readings"] is False and "asthma" in status["health_groups"]
    o = app.get("/api/overview?city=Pune").json()
    assert o["forecast"] and o["measured"]["aqi"] > 0 and o["weather"]["current"]["temperature_2m"] == 27.0
    assert app.get("/api/overview?city=Delhi").status_code == 404
    s = app.get("/api/stations?city=Pune").json()
    assert s["source"] == "archive" and all(st["category"]["name"] for st in s["stations"])
    a = app.get("/api/area?lat=18.507&lon=73.807").json()
    assert a["city"] == "Pune" and a["place"] == "Test Nagar, Pune" and a["measured"]["used"] >= 1 and a["forecast"]
    far = app.get("/api/area?lat=18.6129&lon=74.5695")  # ~75 km east of Pune
    assert far.status_code == 404 and far.json()["detail"]["nearest_city"] == "Pune" and 60 < far.json()["detail"]["km"] < 90
    m = app.get("/api/model").json()
    # Four methods at each of 7 horizons, all on the same rows; significance is reported, never assumed.
    assert len(m["horizons"]) == 28 and {h["Method"] for h in m["horizons"]} == {m["airaware"], m["persistence"], m["history_only"], m["optimistic"]}
    assert 0 <= m["dm"]["p"] <= 1 and 0 <= m["dm_history"]["p"] <= 1 and m["vintage"] is True
    i = app.get("/api/insights?city=Mumbai").json()
    assert len(i["hourly"]) == 12 * 24 and i["cigarettes_year"] > 0 and len(i["weekday"]) == 7
    t = app.get("/api/track-record").json()
    assert t["pending"] > 0  # startup logged the current forecasts
    assert app.get("/api/health").json() == {"ok": True}


def test_writes_need_the_header(app):
    r = app.post("/api/auth/signup", json={"email": "x@example.com", "name": "X", "password": "longenough"})
    assert r.status_code == 403  # no X-AirAware header: a cross-site form cannot do this


def test_signup_login_logout_and_profile(app):
    c = client(app)
    r = signup(c, "asha@example.com")
    assert r.status_code == 201 and r.json()["role"] == "user"
    assert signup(client(app), "ASHA@example.com").status_code == 409  # emails are case-insensitive
    assert signup(client(app), "bad-email").status_code == 422
    assert signup(client(app), "short@example.com", password="1234").status_code == 422

    me = c.get("/api/auth/me").json()
    assert me["user"]["email"] == "asha@example.com" and me["unread"] == 0
    p = c.patch("/api/me", json={"health": ["asthma"], "health_consent": True, "city": "Mumbai"}, headers=H).json()
    assert p["health"] == ["asthma"] and p["city"] == "Mumbai"
    assert c.patch("/api/me", json={"health": ["vampire"]}, headers=H).status_code == 422

    # personal advice follows the profile: the same forecast reads stricter for someone with asthma
    o = c.get("/api/overview?city=Pune").json()
    assert all("personal" in f for f in o["forecast"])

    c.post("/api/auth/logout", headers=H)
    assert c.get("/api/auth/me").json()["user"] is None
    assert c.post("/api/auth/login", json={"email": "asha@example.com", "password": "wrong password"}, headers=H).status_code == 401
    assert c.post("/api/auth/login", json={"email": "Asha@Example.com", "password": "correct horse"}, headers=H).status_code == 200
    assert c.get("/api/auth/me").json()["user"]["name"] == "Asha"


def test_password_is_hashed_and_session_token_not_stored(app):
    c = client(app)
    signup(c, "hash@example.com", password="s3cret-pass")
    u = db.one("SELECT pw_hash FROM users WHERE email = ?", ("hash@example.com",))
    assert u["pw_hash"].startswith("scrypt$") and "s3cret" not in u["pw_hash"]
    token = c.cookies.get(auth.COOKIE)
    assert token and not db.one("SELECT 1 FROM sessions WHERE token_hash = ?", (token,))


def test_login_limit_per_email_whatever_the_address(app, monkeypatch):
    monkeypatch.setattr(auth, "LOGIN_LIMIT", 3)
    signup(client(app), "target@example.com", password="right-password")
    c = client(app)
    for _ in range(3):
        c.post("/api/auth/login", json={"email": "target@example.com", "password": "nope-nope"}, headers=H)
    r = c.post("/api/auth/login", json={"email": "target@example.com", "password": "right-password"}, headers=H)
    assert r.status_code == 429  # even the right password waits out the window
    assert not auth.allow_login("198.51.100.7", "target@example.com")  # a new address does not reset the email's count
    assert auth.allow_login("198.51.100.7", "someone-else@example.com")


def test_take_cleanup_keeps_other_actions_rows():
    old = "2000-01-01T00:00:00+00:00"
    db.run("INSERT INTO throttle (action, key, at) VALUES ('long', 'k', ?)", (old,))
    db.run("INSERT INTO throttle (action, key, at) VALUES ('long', 'k', ?)", (db.now(),))
    assert db.take("short", "k", 5, 1)  # cleans up 'short' rows only
    assert db.one("SELECT COUNT(*) AS n FROM throttle WHERE action = 'long'")["n"] == 2


def test_take_is_atomic_under_parallel_requests():
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(16) as ex:
        results = list(ex.map(lambda _: db.take("race", "k", 5, 60), range(40)))
    assert sum(results) == 5


def test_ipv6_visitors_are_grouped_by_64():
    assert auth.visitor("2001:db8::1") == auth.visitor("2001:db8::ffff:1") == "2001:db8::/64"
    assert auth.visitor("2001:db8:0:1::1") != auth.visitor("2001:db8::1")
    assert auth.visitor("10.1.2.3") == "10.1.2.3"


def test_places_alerts_and_notifications(app):
    c = client(app)
    signup(c, "places@example.com")
    assert c.get("/api/me/places").status_code == 200
    assert client(app).get("/api/me/places").status_code == 401
    pid = c.post("/api/me/places", json={"name": "Home", "lat": 18.52, "lon": 73.85}, headers=H).json()["id"]
    assert c.post("/api/me/places", json={"name": "Delhi", "lat": 28.6, "lon": 77.2}, headers=H).status_code == 422
    places = c.get("/api/me/places").json()
    assert places[0]["name"] == "Home" and places[0]["forecast"]

    # an alert at the lowest threshold fires straight away, once per target day
    aid = c.post("/api/me/alerts", json={"place_id": pid, "threshold": 50}, headers=H).json()["id"]
    notes = c.get("/api/me/notifications").json()
    assert len(notes) == 1 and "Home" in notes[0]["title"]
    core.check_alerts(server.app.state.core)
    assert len(c.get("/api/me/notifications").json()) == 1
    assert c.get("/api/auth/me").json()["unread"] == 1
    c.post("/api/me/notifications/read", headers=H)
    assert c.get("/api/auth/me").json()["unread"] == 0

    other = client(app)
    signup(other, "intruder@example.com")
    assert other.delete(f"/api/me/alerts/{aid}", headers=H).status_code == 404  # cannot touch someone else's alert
    assert other.post("/api/me/alerts", json={"place_id": pid, "threshold": 100}, headers=H).status_code == 404
    assert c.delete(f"/api/me/places/{pid}", headers=H).json() == {"ok": True}
    assert db.one("SELECT COUNT(*) AS n FROM alerts WHERE id = ?", (aid,))["n"] == 0  # alerts go with their place


def test_reports_and_admin_moderation(app):
    c = client(app)
    signup(c, "reporter@example.com")
    assert client(app).post("/api/reports", json={"lat": 18.52, "lon": 73.85, "kind": "burning"}, headers=H).status_code == 401
    assert c.post("/api/reports", json={"lat": 18.52, "lon": 73.85, "kind": "aliens"}, headers=H).status_code == 422
    rid = c.post("/api/reports", json={"lat": 18.52, "lon": 73.85, "kind": "burning", "note": "Leaves on fire"}, headers=H).json()["id"]
    assert app.get("/api/reports?city=Pune").json() == []  # not public until approved

    assert c.get("/api/admin/overview").status_code == 403
    boss = client(app)
    assert signup(boss, "boss@example.com", name="Boss").json()["role"] == "user"  # signing up never makes an admin
    assert boss.get("/api/admin/overview").status_code == 403
    assert manage.main(["make-admin", "boss@example.com"]) == 0  # only the server's command line can
    ov = boss.get("/api/admin/overview").json()
    assert ov["counts"]["reports_pending"] >= 1 and ov["freshness"]
    pending = boss.get("/api/admin/reports?status=pending").json()
    assert any(r["id"] == rid and r["author"] == "reporter@example.com" for r in pending)
    boss.patch(f"/api/admin/reports/{rid}", json={"status": "approved"}, headers=H)
    assert app.get("/api/reports?city=Pune").json()[0]["note"] == "Leaves on fire"
    assert app.get("/api/area?lat=18.52&lon=73.85").json()["reports"]

    reporter_id = db.one("SELECT id FROM users WHERE email = ?", ("reporter@example.com",))["id"]
    boss.patch(f"/api/admin/users/{reporter_id}", json={"disabled": True}, headers=H)
    assert c.get("/api/auth/me").json()["user"] is None  # disabling ends their sessions
    me_id = db.one("SELECT id FROM users WHERE email = ?", ("boss@example.com",))["id"]
    assert boss.patch(f"/api/admin/users/{me_id}", json={"role": "user"}, headers=H).status_code == 422
    assert any(a["action"] == "admin.disable" for a in boss.get("/api/admin/audit").json())
    assert boss.get("/api/admin/stations").json() and boss.get("/api/admin/jobs").json()[-1]["kind"] == "startup"


def test_delete_account(app):
    c = client(app)
    signup(c, "leaver@example.com", password="goodbye-123")
    assert c.request("DELETE", "/api/me", json={"email": "leaver@example.com", "password": "wrong-one"}, headers=H).status_code == 403
    assert c.request("DELETE", "/api/me", json={"email": "leaver@example.com", "password": "goodbye-123"}, headers=H).json() == {"ok": True}
    assert not db.one("SELECT 1 FROM users WHERE email = ?", ("leaver@example.com",))


def test_forecast_log_is_scored_when_actuals_arrive(app):
    s = server.app.state.core
    row = db.one("SELECT * FROM forecast_log WHERE actual IS NULL LIMIT 1")
    d = s.daily.copy()
    d.loc[(d["city"] == row["city"]) & (d["date"] == pd.Timestamp(row["target"])), "aqi"] = 123.0
    assert core.score_forecasts(d) >= 1
    assert db.one("SELECT actual FROM forecast_log WHERE city = ? AND target = ?", (row["city"], row["target"]))["actual"] == 123
    t = app.get("/api/track-record").json()
    assert t["scored"] >= 1 and t["horizons"]


def test_live_readings_start_the_forecast_today():
    st = pd.DataFrame({"station": ["A", "B"], "city": "Pune"})
    today = pd.Timestamp.today().normalize()
    daily = pd.DataFrame({"date": [today], "city": ["Pune"], "aqi": [float("nan")], "pm25": [float("nan")], "pm10": [float("nan")], "stations": [0.0]})
    readings = pd.DataFrame({"station": ["A", "B"], "aqi": [100.0, 120.0], "pm25": [40.0, 50.0], "pm10": [100.0, 120.0]})
    d = core.with_live_day(daily, readings, st)
    assert d.loc[0, "aqi"] == 110 and d.loc[0, "stations"] == 2


def test_openaq_parsing(monkeypatch):
    hours = [{"value": v, "period": {"datetimeTo": {"local": f"2026-10-09T{h:02d}:00:00+05:30"}}} for h, v in enumerate([45.0] * 20 + [999.0])]

    def fake(url, params, headers=None):
        if url.endswith("/locations/1"):
            return {"results": [{"coordinates": {"latitude": 18.5, "longitude": 73.8},
                                 "sensors": [{"id": 11, "parameter": {"name": "pm25"}}, {"id": 12, "parameter": {"name": "no2"}}]}]}
        return {"results": hours}
    monkeypatch.setattr(live, "_json", fake)
    df = live.openaq_latest({1: "Test"}, key="k", pause=0)
    assert len(df) == 1 and df.loc[0, "pm25"] == 45 and df.loc[0, "aqi"] == 75  # 999 error code dropped


def test_openaq_skips_stations_silent_past_the_window(monkeypatch):
    calls = []

    def fake(url, params, headers=None):
        calls.append(url)
        return {"results": [{"datetimeLast": {"utc": "2022-07-07T04:45:00Z"}, "coordinates": {"latitude": 18.5, "longitude": 73.8},
                             "sensors": [{"id": 11, "parameter": {"name": "pm25"}}]}]}
    monkeypatch.setattr(live, "_json", fake)
    assert live.openaq_latest({1: "Retired"}, key="k", pause=0).empty
    assert calls == [f"{live.OPENAQ}/locations/1"]  # no sensor calls spent on a station with nothing recent


def test_outbound_calls_are_throttled_and_cache_is_bounded(monkeypatch):
    calls = []

    class Resp:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self): return b"{}"

    waits = []
    monkeypatch.setattr(live.urllib.request, "urlopen", lambda req, timeout: calls.append(req.full_url) or Resp())
    monkeypatch.setattr(live.time, "sleep", waits.append)
    monkeypatch.setattr(live, "_last_call", {})
    for i in range(3):  # Nominatim: one a second, so these queue at 0 s, +1 s and +2 s
        live._json(live.GEOCODE, {"lat": i})
    assert len(calls) == 3 and [round(w) for w in waits] == [1, 2]
    with pytest.raises(live.Throttled):  # the next would wait 3 s, more than MAX_WAIT: refused without a request
        live._json(live.GEOCODE, {"lat": 9})
    assert len(calls) == 3

    monkeypatch.setattr(live, "_cache", {})
    monkeypatch.setattr(live, "CACHE_SIZE", 3)
    for i in range(5):
        live.cached(("k", i), 60, lambda i=i: i)
    assert list(live._cache) == [("k", 2), ("k", 3), ("k", 4)]


def test_area_limit_per_visitor_groups_ipv6_and_caps_memory(monkeypatch):
    monkeypatch.setattr(public, "_hits", {})
    assert all(public.allow("1.2.3.4") for _ in range(public.AREA_PER_MINUTE))
    assert not public.allow("1.2.3.4") and public.allow("5.6.7.8")
    assert all(public.allow(f"2001:db8::{i:x}") for i in range(public.AREA_PER_MINUTE))
    assert not public.allow("2001:db8::ffff")  # same /64, same visitor
    monkeypatch.setattr(public, "MAX_VISITORS", 5)
    for i in range(20):
        public.allow(f"10.0.0.{i}")
    assert len(public._hits) == 5 and "10.0.0.19" in public._hits


def test_signups_are_limited_per_network(app, monkeypatch):
    monkeypatch.setattr(account, "SIGNUPS_PER_HOUR", 0)
    assert signup(client(app), "spammer@example.com").status_code == 429


def test_hour_shape_keeps_the_daily_mean():
    profile = pd.DataFrame({"city": "Pune", "month": 1, "hour": range(24), "aqi": [100.0] * 12 + [200.0] * 12})
    h = public.hour_shape(profile, "Pune", pd.Timestamp("2026-01-05"), 90.0)
    assert len(h) == 24 and abs(sum(x["aqi"] for x in h) / 24 - 90) < 1e-9 and h[0]["aqi"] == 60 and h[23]["aqi"] == 120


def test_personal_responses_are_marked_for_the_service_worker(app):
    assert "x-airaware-personal" not in app.get("/api/overview?city=Pune").headers
    c = client(app)
    signup(c, "private@example.com")
    assert c.get("/api/overview?city=Pune").headers["x-airaware-personal"] == "1"
    assert c.get("/api/area?lat=18.52&lon=73.85").headers["x-airaware-personal"] == "1"


def test_password_reset_by_admin_link(app):
    c = client(app)
    signup(c, "forgetful@example.com", password="old-password-1")
    assert client(app).post("/api/auth/forgot", json={"email": "forgetful@example.com"}, headers=H).json()["ok"]
    assert client(app).post("/api/auth/forgot", json={"email": "nobody-here@example.com"}, headers=H).json()["ok"]  # same answer

    boss = client(app)
    signup(boss, "resetter@example.com")
    manage.main(["make-admin", "resetter@example.com"])
    uid = db.one("SELECT id FROM users WHERE email = ?", ("forgetful@example.com",))["id"]
    assert c.post(f"/api/admin/users/{uid}/reset-link", headers=H).status_code == 403
    path = boss.post(f"/api/admin/users/{uid}/reset-link", headers=H).json()["path"]
    token = path.split("token=")[1]
    assert not db.one("SELECT 1 FROM password_resets WHERE token_hash = ?", (token,))  # only the hash is stored

    assert client(app).post("/api/auth/reset", json={"token": token, "password": "short"}, headers=H).status_code == 422
    assert client(app).post("/api/auth/reset", json={"token": token, "password": "new-password-2"}, headers=H).json() == {"ok": True}
    assert client(app).post("/api/auth/reset", json={"token": token, "password": "new-password-3"}, headers=H).status_code == 400  # single use
    assert c.get("/api/auth/me").json()["user"] is None  # old sessions ended
    assert client(app).post("/api/auth/login", json={"email": "forgetful@example.com", "password": "new-password-2"}, headers=H).status_code == 200


def test_password_change_voids_outstanding_reset_links(app):
    c = client(app)
    signup(c, "careful@example.com", password="first-password")
    uid = db.one("SELECT id FROM users WHERE email = ?", ("careful@example.com",))["id"]
    leaked = auth.new_reset_token(uid, hours=24)
    c.post("/api/me/password", json={"current": "first-password", "new": "second-password"}, headers=H)
    assert auth.use_reset_token(leaked) is None


def test_reset_tokens_expire_and_are_replaced():
    uid = db.run("INSERT INTO users (email, name, pw_hash, created_at) VALUES ('exp@example.com', 'E', 'x', ?)", (db.now(),))
    first = auth.new_reset_token(uid, hours=1)
    second = auth.new_reset_token(uid, hours=1)
    assert auth.use_reset_token(first) is None and auth.use_reset_token(second) == uid  # a new link voids the old one
    old = auth.new_reset_token(uid, hours=-1)
    assert auth.use_reset_token(old) is None


def test_backups_are_complete_and_rotated(app):
    import sqlite3
    f = db.backup()
    with sqlite3.connect(f) as con:
        assert con.execute("SELECT COUNT(*) FROM users").fetchone()[0] == db.one("SELECT COUNT(*) AS n FROM users")["n"]
    for day in range(1, 10):  # nine more days of backups: only the newest seven survive
        (f.parent / f"airaware-2000-01-{day:02d}.db").write_bytes(b"")
    db.backup(keep=7)
    assert len(list(f.parent.glob("airaware-*.db"))) == 7 and f.exists()

    boss = client(app)
    signup(boss, "backup-admin@example.com")
    manage.main(["make-admin", "backup-admin@example.com"])
    r = boss.post("/api/admin/backup", headers=H)
    assert r.status_code == 200 and r.content[:16] == b"SQLite format 3\x00"
    assert client(app).post("/api/admin/backup", headers=H).status_code == 401


def test_password_rechecks_are_capped_per_account(app):
    c = client(app)
    signup(c, "hammer@example.com", password="real-password")
    codes = [c.post("/api/me/password", json={"current": "wrong-guess", "new": "another-pass"}, headers=H).status_code for _ in range(6)]
    assert codes == [403] * 5 + [429]
    assert c.request("DELETE", "/api/me", json={"email": "hammer@example.com", "password": "real-password"}, headers=H).status_code == 429


def test_search_by_name(app):
    r = app.get("/api/search?q=Kothrud&city=Pune")
    assert r.status_code == 200 and r.json()[0]["name"] == "Kothrud"
    assert app.get("/api/search?q=K&city=Pune").status_code == 422  # too short
    assert app.get("/api/search?q=Kothrud&city=Delhi").status_code == 404


def test_validation_errors_never_echo_input_or_crash(app):
    c = client(app)
    signup(c, "echo@example.com")
    r = c.post("/api/me/places", content='{"name": "n", "lat": NaN, "lon": 73.8}', headers={**H, "Content-Type": "application/json"})
    assert r.status_code == 422 and "lat" in r.json()["detail"]
    r = c.post("/api/auth/login", json={"email": "x@example.com", "password": "secret-" + "p" * 300}, headers=H)
    assert r.status_code == 422 and "secret-" not in r.text  # the password is not repeated back
    assert c.post("/api/auth/login", content="x" * 70_000, headers={**H, "Content-Type": "application/json"}).status_code == 413


def test_dpdp_consent_rights_and_retention(app):
    # sign-up needs agreement to the terms and an adult confirmation
    r = client(app).post("/api/auth/signup", json={"email": "noconsent@example.com", "name": "N", "password": "long-enough-1", "city": "Pune"}, headers=H)
    assert r.status_code == 422
    c = client(app)
    u = signup(c, "rights@example.com").json()
    assert u["needs_consent"] is False and u["health_consent"] is False

    # health information needs its own explicit consent, and withdrawing it erases it
    assert c.patch("/api/me", json={"health": ["asthma"]}, headers=H).status_code == 422
    assert c.patch("/api/me", json={"health": ["asthma"], "health_consent": True}, headers=H).json()["health"] == ["asthma"]
    w = c.delete("/api/me/health", headers=H).json()
    assert w["health"] == [] and w["health_consent"] is False

    # a copy of everything, without the password hash
    c.post("/api/me/places", json={"name": "Work", "lat": 18.53, "lon": 73.85}, headers=H)
    data = c.get("/api/me/export").json()
    assert data["profile"]["email"] == "rights@example.com" and "pw_hash" not in data["profile"]
    assert data["places"][0]["name"] == "Work" and any(a["action"] == "consent.given" for a in data["activity_log"])

    # anyone can file a request or grievance; admins see and resolve it
    rid = client(app).post("/api/privacy/requests", json={"email": "outsider@example.com", "kind": "grievance", "message": "Please explain my data."}, headers=H).json()["id"]
    assert client(app).post("/api/privacy/requests", json={"email": "x@example.com", "kind": "hack", "message": "hello there"}, headers=H).status_code == 422
    boss = client(app)
    signup(boss, "dpo@example.com")
    manage.main(["make-admin", "dpo@example.com"])
    assert any(q["id"] == rid for q in boss.get("/api/admin/privacy-requests").json())
    assert boss.patch(f"/api/admin/privacy-requests/{rid}", json={"response": "Replied by email with a summary."}, headers=H).json() == {"ok": True}

    # retention: old read notifications go, recent ones stay
    uid = db.one("SELECT id FROM users WHERE email = ?", ("rights@example.com",))["id"]
    db.run("INSERT INTO notifications (user_id, title, body, created_at, read) VALUES (?, 'old', 'x', '2000-01-01T00:00:00+00:00', 1)", (uid,))
    db.run("INSERT INTO notifications (user_id, title, body, created_at, read) VALUES (?, 'new', 'x', ?, 1)", (uid, db.now()))
    gone = db.apply_retention()
    assert gone["read notifications"] >= 1
    assert [n["title"] for n in db.rows("SELECT title FROM notifications WHERE user_id = ?", (uid,))] == ["new"]


def test_existing_users_are_asked_to_agree_to_new_terms(app):
    c = client(app)
    signup(c, "oldtimer@example.com")
    db.run("UPDATE users SET terms_version = NULL WHERE email = 'oldtimer@example.com'")
    assert c.get("/api/auth/me").json()["user"]["needs_consent"] is True
    assert c.post("/api/me/consent", headers=H).json()["needs_consent"] is False


def test_two_step_sign_in(app, monkeypatch):
    import time as _time
    c = client(app)
    signup(c, "twostep@example.com", password="two-step-pass")
    manage.main(["make-admin", "twostep@example.com"])
    monkeypatch.setenv("AIRAWARE_ADMIN_2FA", "1")
    assert c.get("/api/admin/overview").status_code == 403  # admins need two-step on

    assert c.post("/api/me/2fa/setup", json={"password": "wrong-password"}, headers=H).status_code == 403  # a stolen session is not enough
    setup = c.post("/api/me/2fa/setup", json={"password": "two-step-pass"}, headers=H).json()
    assert setup["uri"].startswith("otpauth://totp/AirAware") and len(setup["secret"]) >= 32
    step = int(_time.time() // 30)
    assert c.post("/api/me/2fa/enable", json={"code": "000000"}, headers=H).status_code == 400
    assert c.post("/api/me/2fa/enable", json={"code": auth.totp_code(setup["secret"], step)}, headers=H).json()["two_step"] is True
    assert c.get("/api/admin/overview").status_code == 200

    fresh = client(app)
    login = {"email": "twostep@example.com", "password": "two-step-pass"}
    assert fresh.post("/api/auth/login", json=login, headers=H).json()["detail"] == "two_step_required"
    used = auth.totp_code(setup["secret"], step)
    assert fresh.post("/api/auth/login", json={**login, "code": used}, headers=H).status_code == 401  # replay of the enable code
    nxt = auth.totp_code(setup["secret"], step + 1)
    assert fresh.post("/api/auth/login", json={**login, "code": nxt}, headers=H).status_code == 200
    assert fresh.post("/api/auth/login", json={**login, "code": nxt}, headers=H).status_code == 401  # same code again
    assert "totp_secret" not in c.get("/api/me/export").json()["profile"]

    assert manage.main(["reset-2fa", "twostep@example.com"]) == 0
    assert c.get("/api/admin/overview").status_code == 403


def test_totp_matches_rfc_6238():
    # RFC 6238 test vector (SHA-1): secret "12345678901234567890", time 59 s -> 94287082 (last 6 digits 287082)
    secret = __import__("base64").b32encode(b"12345678901234567890").decode().rstrip("=")
    assert auth.totp_code(secret, 59 // 30) == "287082"


def test_forwarded_address_trusted_only_from_the_proxy(monkeypatch):
    from starlette.requests import Request as R

    def req(host, headers):
        return R({"type": "http", "client": (host, 1), "headers": [(k.encode(), v.encode()) for k, v in headers.items()], "scheme": "http",
                  "server": ("x", 80), "path": "/", "query_string": b""})
    monkeypatch.setenv("AIRAWARE_TRUSTED_PROXIES", "172.30.0.20")
    assert auth.client_ip(req("172.30.0.20", {"cf-connecting-ip": "203.0.113.5"})) == "203.0.113.5"
    assert auth.client_ip(req("10.0.0.9", {"cf-connecting-ip": "203.0.113.5"})) == "10.0.0.9"  # forged header ignored
    assert auth.via_https(req("172.30.0.20", {"x-forwarded-proto": "https"}))
    assert not auth.via_https(req("10.0.0.9", {"x-forwarded-proto": "https"}))
    # A host's edge network (Railway): trust a range, and read only the header that edge sets.
    monkeypatch.setenv("AIRAWARE_TRUSTED_PROXIES", "100.64.0.0/10")
    monkeypatch.setenv("AIRAWARE_CLIENT_IP_HEADER", "X-Real-IP")
    edge = {"x-real-ip": "198.51.100.7", "cf-connecting-ip": "203.0.113.5", "x-forwarded-for": "203.0.113.6"}
    assert auth.client_ip(req("100.64.3.9", edge)) == "198.51.100.7"
    assert auth.client_ip(req("8.8.8.8", edge)) == "8.8.8.8"
    assert auth.client_ip(req("not-an-ip", edge)) == "not-an-ip"
    assert auth.client_ip(req("100.64.3.9", {"x-real-ip": "198.51.100.7:51234"})) == "198.51.100.7"
    assert auth.client_ip(req("100.64.3.9", {"x-real-ip": "[2001:db8::1]:443"})) == "2001:db8::1"
    assert auth.client_ip(req("100.64.3.9", {"x-real-ip": "garbage, or empty"})) == "100.64.3.9"


def test_rebuild_clock_survives_restarts(app):
    db.run("DELETE FROM jobs WHERE kind LIKE '%rebuild%'")
    assert core.hours_since_rebuild() == float("inf")
    db.run("INSERT INTO jobs (kind, started_at, finished_at, ok) VALUES ('manual rebuild', ?, ?, 1)", (db.now(), db.now()))
    assert core.hours_since_rebuild() < 0.1


def test_link_previews_use_a_safe_absolute_origin(app, monkeypatch, tmp_path):
    (tmp_path / "index.html").write_text('<meta property="og:image" content="__ORIGIN__/og.png">')
    monkeypatch.setattr(server, "DIST", tmp_path)
    r = app.get("/", headers={"Host": "evil.example"})
    assert 'content="/og.png"' in r.text and "evil" not in r.text  # the Host header is never used
    assert r.headers["cache-control"] == "no-cache, private"
    monkeypatch.setenv("AIRAWARE_PUBLIC_URL", "https://airaware.in/")
    assert 'content="https://airaware.in/og.png"' in app.get("/me", headers={"Host": "evil.example"}).text
    monkeypatch.setenv("AIRAWARE_PUBLIC_URL", 'https://x.in/"><script>')
    assert "<script>" not in app.get("/").text


def test_make_admin_from_env_only_bootstraps_the_first_admin(app, monkeypatch):
    for row in db.rows("SELECT id FROM users WHERE role = 'admin'"):   # earlier tests may have made admins
        db.run("UPDATE users SET role = 'user' WHERE id = ?", (row["id"],))
    signup(app, "owner@example.com")
    monkeypatch.setenv("AIRAWARE_MAKE_ADMIN", " Owner@example.com , nobody@example.com")
    server.promote_listed_admins()
    assert db.one("SELECT role FROM users WHERE email = 'owner@example.com'")["role"] == "admin"
    assert db.one("SELECT COUNT(*) AS n FROM users WHERE email = 'nobody@example.com'")["n"] == 0
    # Demoted (no admin left) with the variable still set: a restart must not promote that email again.
    db.run("UPDATE users SET role = 'user' WHERE email = 'owner@example.com'")
    server.promote_listed_admins()
    assert db.one("SELECT role FROM users WHERE email = 'owner@example.com'")["role"] == "user"
    # Once any admin exists, nobody else is promoted by the variable.
    signup(app, "late@example.com")
    db.run("UPDATE users SET role = 'admin' WHERE email = 'owner@example.com'")
    monkeypatch.setenv("AIRAWARE_MAKE_ADMIN", "late@example.com")
    server.promote_listed_admins()
    assert db.one("SELECT role FROM users WHERE email = 'late@example.com'")["role"] == "user"


# ---------- pollution reports: CRUD, filters, statistics, permissions, the database being offline ----------

def _report(c, lat=18.52, lon=73.85, kind="construction", note=""):
    return c.post("/api/reports", json={"lat": lat, "lon": lon, "kind": kind, "note": note}, headers=H)


def test_report_crud_filters_and_permissions(app):
    alice, bob, mod = client(app), client(app), client(app)
    signup(alice, "alice-r@example.com")
    signup(bob, "bob-r@example.com")
    signup(mod, "mod-r@example.com")
    manage.main(["make-admin", "mod-r@example.com"])
    rid = _report(alice, note="dust from a site").json()["id"]
    assert _report(alice, lat=28.6, lon=77.2).status_code == 422  # Delhi is outside the coverage
    assert _report(alice, note="x" * 281).status_code == 422
    # Update and delete are the author's own business.
    assert bob.patch(f"/api/me/reports/{rid}", json={"kind": "other", "note": "mine now"}, headers=H).status_code == 404
    assert bob.delete(f"/api/me/reports/{rid}", headers=H).status_code == 404
    assert alice.patch(f"/api/me/reports/{rid}", json={"kind": "aliens"}, headers=H).status_code == 422
    assert alice.patch(f"/api/me/reports/{rid}", json={"kind": "burning", "note": "leaf burning"}, headers=H).status_code == 200
    assert [r["kind"] for r in alice.get("/api/me/reports").json() if r["id"] == rid] == ["burning"]
    # Moderation is for admins only.
    for c in (alice, bob):
        assert c.get("/api/admin/reports").status_code == 403 and c.get("/api/admin/reports/stats").status_code == 403
        assert c.patch(f"/api/admin/reports/{rid}", json={"status": "approved"}, headers=H).status_code == 403
        assert c.delete(f"/api/admin/reports/{rid}", headers=H).status_code == 403
    assert client(app).get("/api/admin/reports").status_code == 401
    # Filters, and refusing nonsense.
    assert any(r["id"] == rid for r in mod.get("/api/admin/reports?status=pending&kind=burning&city=Pune").json())
    assert not any(r["id"] == rid for r in mod.get("/api/admin/reports?status=all&city=Mumbai").json())
    today = pd.Timestamp.now(tz="UTC").date().isoformat()
    assert any(r["id"] == rid for r in mod.get(f"/api/admin/reports?status=all&since={today}&until={today}").json())
    for bad in ("status=maybe", "kind=aliens", "city=Delhi", "since=yesterday", "until=2026-13-40"):
        assert mod.get(f"/api/admin/reports?{bad}").status_code == 422, bad
    assert mod.patch(f"/api/admin/reports/{rid}", json={"status": "deleted"}, headers=H).status_code == 422
    assert mod.patch("/api/admin/reports/999999", json={"status": "approved"}, headers=H).status_code == 404
    assert mod.patch(f"/api/admin/reports/{rid}", json={"status": "approved"}, headers=H).status_code == 200
    public = app.get("/api/reports?city=Pune").json()
    assert any(r["id"] == rid for r in public) and all("user_id" not in r and "author" not in r for r in public)
    # Judged: the author can no longer edit it, but can still withdraw it.
    assert alice.patch(f"/api/me/reports/{rid}", json={"kind": "other", "note": ""}, headers=H).status_code == 404
    s = mod.get("/api/admin/reports/stats?days=30").json()
    assert s["by_status"]["approved"] >= 1 and s["backend"] == "sqlite" and any(x["kind"] == "burning" for x in s["by_city_kind"])
    assert alice.delete(f"/api/me/reports/{rid}", headers=H).status_code == 200
    assert not any(r["id"] == rid for r in app.get("/api/reports?city=Pune").json())
    spam = _report(bob, note="buy cheap stuff").json()["id"]
    assert mod.delete(f"/api/admin/reports/{spam}", headers=H).status_code == 200
    assert mod.delete(f"/api/admin/reports/{spam}", headers=H).status_code == 404
    assert any(a["action"] == "admin.report_deleted" for a in mod.get("/api/admin/audit").json())


def test_reports_database_offline_is_explicit_and_contained(app, monkeypatch):
    c, boss = client(app), client(app)
    signup(c, "offline-user@example.com", password="offline-pass-1")
    signup(boss, "offline-admin@example.com")
    manage.main(["make-admin", "offline-admin@example.com"])
    monkeypatch.setenv("AIRAWARE_MONGO_URL", "mongodb://127.0.0.1:1")  # configured, but nothing listens there
    r = app.get("/api/reports?city=Pune")
    assert r.status_code == 503 and "offline" in r.json()["detail"]
    assert _report(c).status_code == 503 and c.get("/api/me/reports").status_code == 503
    area = app.get("/api/area?lat=18.52&lon=73.85")  # the forecast still works
    assert area.status_code == 200 and area.json()["reports"] == [] and area.json()["reports_available"] is False
    ov = boss.get("/api/admin/overview").json()
    assert ov["counts"]["reports"] is None and ov["reports_store"] == {"backend": "mongodb", "ok": False, "error": ov["reports_store"]["error"]}
    assert boss.get("/api/admin/reports").status_code == 503 and boss.get("/api/admin/users").json()[0]["reports"] is None
    # Export and account deletion refuse rather than silently skipping the reports.
    assert c.get("/api/me/export").status_code == 503
    assert c.request("DELETE", "/api/me", json={"email": "offline-user@example.com", "password": "offline-pass-1"}, headers=H).status_code == 503
    assert c.get("/api/auth/me").json()["user"]["email"] == "offline-user@example.com"
    monkeypatch.delenv("AIRAWARE_MONGO_URL")
    assert app.get("/api/reports?city=Pune").status_code == 200  # back on SQLite


@pytest.mark.skipif(not os.environ.get("AIRAWARE_TEST_MONGO_URL"), reason="set AIRAWARE_TEST_MONGO_URL for the MongoDB API test")
def test_report_api_on_a_real_mongodb(app, monkeypatch):
    import uuid
    name = f"airaware_api_{uuid.uuid4().hex[:8]}"
    monkeypatch.setenv("AIRAWARE_MONGO_URL", os.environ["AIRAWARE_TEST_MONGO_URL"])
    monkeypatch.setenv("AIRAWARE_MONGO_DB", name)
    from airaware.server import reports
    reports._store = None
    try:
        c, boss = client(app), client(app)
        signup(c, "mongo-user@example.com", password="mongo-pass-123")
        signup(boss, "mongo-admin@example.com")
        manage.main(["make-admin", "mongo-admin@example.com"])
        rid = _report(c, kind="industry", note="black smoke").json()["id"]
        assert len(rid) == 24  # a MongoDB ObjectId
        assert boss.patch(f"/api/admin/reports/{rid}", json={"status": "approved"}, headers=H).status_code == 200
        assert any(r["id"] == rid for r in app.get("/api/reports?city=Pune").json())
        assert app.get("/api/area?lat=18.52&lon=73.85").json()["reports"][0]["id"] == rid  # the 2dsphere $nearSphere query
        s = boss.get("/api/admin/reports/stats").json()
        assert s["backend"] == "mongodb" and s["by_status"]["approved"] == 1 and s["moderated"] == 1
        assert boss.get("/api/admin/overview").json()["reports_store"] == {"backend": "mongodb", "ok": True}
        assert [r["id"] for r in c.get("/api/me/export").json()["reports"]] == [rid]
        assert c.request("DELETE", "/api/me", json={"email": "mongo-user@example.com", "password": "mongo-pass-123"}, headers=H).status_code == 200
        assert boss.get(f"/api/admin/reports?status=all").json()[0]["author"] is None  # kept, without the author
    finally:
        reports.store().client.drop_database(name)
        reports._store = None


def test_a_deleted_accounts_id_is_never_reused(app):
    """Reports in MongoDB refer to authors by SQLite id, with no foreign key to clear them, so a new account must never
    inherit a deleted one's id (SQLite reuses the highest id after it is deleted unless told otherwise)."""
    c = client(app)
    signup(c, "last-in@example.com", password="last-in-pass-1")
    old_id = db.one("SELECT id FROM users WHERE email = 'last-in@example.com'")["id"]
    assert old_id == db.one("SELECT MAX(id) AS m FROM users")["m"]  # the highest id: exactly the case SQLite would reuse
    assert c.request("DELETE", "/api/me", json={"email": "last-in@example.com", "password": "last-in-pass-1"}, headers=H).status_code == 200
    assert db.one("SELECT COUNT(*) AS n FROM retired_user_ids WHERE id = ?", (old_id,))["n"] == 1
    signup(client(app), "next-in@example.com")
    assert db.one("SELECT id FROM users WHERE email = 'next-in@example.com'")["id"] > old_id
    db.run("DELETE FROM users WHERE email = 'next-in@example.com'")  # any deletion path retires the id (a trigger)
    signup(client(app), "third-in@example.com")
    assert db.one("SELECT id FROM users WHERE email = 'third-in@example.com'")["id"] > old_id + 1
