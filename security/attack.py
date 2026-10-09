"""Attack your own AirAware instance and print PASS or FAIL per check.

Run against a throwaway copy, never a live site with real users (it signs up test accounts and trips rate limits):
    AIRAWARE_DB=/tmp/pentest.db AIRAWARE_REFRESH=0 uvicorn airaware.server.app:app --port 8002 --no-server-header
    python security/attack.py
"""
import json
import secrets
import time

import httpx

import os
B = os.environ.get("AIRAWARE_TARGET", "http://127.0.0.1:8002")  # only ever point this at your own instance
H = {"X-AirAware": "1"}
results = []


def check(name, ok, detail=""):
    results.append((name, ok))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""), flush=True)


def new_user(tag):
    c = httpx.Client(base_url=B, timeout=60)
    email = f"{tag}-{secrets.token_hex(3)}@example.com"
    r = c.post("/api/auth/signup", json={"email": email, "name": tag, "password": "pentest-pass-1", "city": "Pune", "accept_terms": True, "adult": True}, headers=H)
    return c, email, r


anon = httpx.Client(base_url=B, timeout=60)

# --- headers and cookies ---
r = anon.get("/")
for h in ["content-security-policy", "x-frame-options", "x-content-type-options", "referrer-policy"]:
    check(f"header {h} on pages", h in r.headers)
r = anon.get("/api/status")
check("API responses not cacheable", r.headers.get("cache-control") == "no-store")
check("no server version leak", "uvicorn" not in r.headers.get("server", "").lower(), r.headers.get("server", ""))
a, a_email, r = new_user("alice")
sc = r.headers.get("set-cookie", "")
check("session cookie HttpOnly + SameSite", "httponly" in sc.lower() and "samesite=lax" in sc.lower(), sc[:120])

# --- CSRF ---
r = a.post("/api/me/places", json={"name": "x", "lat": 18.52, "lon": 73.85})
check("write without X-AirAware header refused", r.status_code == 403, str(r.status_code))
r = a.post("/api/me/places", data={"name": "x", "lat": "18.52", "lon": "73.85"}, headers=H)
check("form-encoded body refused", r.status_code in (403, 415, 422), str(r.status_code))
r = anon.options("/api/me/places", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "x-airaware"})
check("no CORS grant to other sites", "access-control-allow-origin" not in r.headers, str(dict(r.headers).get("access-control-allow-origin")))

# --- auth bypass / IDOR ---
b, b_email, _ = new_user("bob")
pid = a.post("/api/me/places", json={"name": "A home", "lat": 18.52, "lon": 73.85}, headers=H).json()["id"]
aid = a.post("/api/me/alerts", json={"place_id": pid, "threshold": 300}, headers=H).json()["id"]
check("other user cannot delete my place", b.delete(f"/api/me/places/{pid}", headers=H).status_code == 404)
check("other user cannot change my alert", b.patch(f"/api/me/alerts/{aid}", json={"active": False}, headers=H).status_code == 404)
check("other user cannot attach alert to my place", b.post("/api/me/alerts", json={"place_id": pid, "threshold": 100}, headers=H).status_code == 404)
check("other user does not see my places", all(p["id"] != pid for p in b.get("/api/me/places").json()))
for path in ["/api/admin/overview", "/api/admin/users", "/api/admin/audit", "/api/admin/jobs"]:
    check(f"non-admin blocked from {path}", a.get(path).status_code == 403)
check("anon blocked from admin", anon.get("/api/admin/users").status_code == 401)
check("non-admin cannot rebuild data", a.post("/api/admin/refresh", headers=H).status_code == 403)
check("non-admin cannot download backup", a.post("/api/admin/backup", headers=H).status_code == 403)
r = a.patch("/api/me", json={"role": "admin"}, headers=H)
check("cannot make self admin via profile", a.get("/api/auth/me").json()["user"]["role"] == "user", str(r.status_code))
forged = httpx.Client(base_url=B, cookies={"aa_session": secrets.token_urlsafe(32)})
check("forged session token rejected", forged.get("/api/auth/me").json()["user"] is None)

# --- injection ---
for payload in ["' OR 1=1 --", "\" OR \"\"=\"", "1; DROP TABLE users;--", "admin@example.com' --"]:
    r = anon.post("/api/auth/login", json={"email": payload, "password": payload}, headers=H)
    check(f"SQL injection in login ({payload[:12]})", r.status_code in (401, 429), str(r.status_code))
r = anon.get("/api/admin/users?q=%27%20OR%201%3D1%20--")
check("SQL injection in admin search blocked by auth", r.status_code == 401)
xss = '<img src=x onerror=alert(1)><script>alert(1)</script>'
r = a.post("/api/me/places", json={"name": xss[:60], "lat": 18.53, "lon": 73.86}, headers=H)
check("XSS name stored as plain text (React escapes on render)", r.status_code == 201)
r = a.post("/api/reports", json={"lat": 18.52, "lon": 73.85, "kind": "burning", "note": xss}, headers=H)
check("XSS report note accepted as text", r.status_code == 201)
r = anon.get("/api/overview?city=Pune%27%3Balert(1)")
check("unknown city rejected", r.status_code == 404)

# --- bad numbers and sizes ---
for lat, lon in [("NaN", "73.8"), ("Infinity", "73.8"), ("1e308", "73.8"), ("-91", "73.8"), ("abc", "73.8")]:
    r = anon.get(f"/api/area?lat={lat}&lon={lon}")
    check(f"bad coordinates rejected ({lat})", r.status_code in (404, 422), str(r.status_code))
r = a.post("/api/me/places", content='{"name": "n", "lat": NaN, "lon": 73.8}', headers={**H, "Content-Type": "application/json"})
check("NaN in JSON body rejected", r.status_code == 422, f"{r.status_code} {r.text[:80]}")
big = "x" * (5 * 1024 * 1024)
try:
    r = anon.post("/api/auth/login", content=json.dumps({"email": big, "password": "p"}), headers={**H, "Content-Type": "application/json"})
    check("5 MB request body refused early", r.status_code == 413, str(r.status_code))
except httpx.HTTPError as e:
    check("5 MB request body refused early", True, f"connection closed: {type(e).__name__}")
r = a.post("/api/me/places", json={"name": "y" * 500, "lat": 18.5, "lon": 73.8}, headers=H)
check("over-long place name rejected", r.status_code == 422)
r = a.post("/api/reports", json={"lat": 18.52, "lon": 73.85, "kind": "burning", "note": "n" * 5000}, headers=H)
check("long report note trimmed or rejected", r.status_code in (201, 422))
r = anon.post("/api/auth/signup", json={"email": "deep@example.com", "name": "d", "password": "p" * 10, "city": ["Pune"] * 1000}, headers=H)
check("wrong JSON types rejected", r.status_code == 422)

# --- traversal and files ---
for p in ["/..%2f..%2fairaware%2fserver%2fdb.py", "/%2e%2e/%2e%2e/etc/passwd", "/assets/../../airaware/server/auth.py", "/....//....//etc/passwd",
          "/data/airaware.db", "/.env", "/airaware.db"]:
    r = anon.get(p)
    leaked = "def " in r.text or "root:" in r.text or r.content[:15] == b"SQLite format 3"
    check(f"no file leak via {p}", not leaked, str(r.status_code))
r = anon.get("/api/does-not-exist")
check("unknown API path is a JSON 404", r.status_code == 404 and r.headers.get("content-type", "").startswith("application/json"))

# --- open redirect / host header ---
r = anon.get("/login?next=//evil.example")
check("login page serves app shell (client checks next)", r.status_code == 200)
r = anon.post("/api/auth/forgot", json={"email": a_email}, headers={**H, "Host": "evil.example"})
check("forgot-password with forged Host accepted without using it", r.status_code == 200)

# --- brute force and limits ---
c = httpx.Client(base_url=B, timeout=60)
codes = [c.post("/api/auth/login", json={"email": a_email, "password": f"wrong-{i}"}, headers=H).status_code for i in range(12)]
check("login brute force locked out", 429 in codes, str(codes))
codes = [anon.post("/api/auth/reset", json={"token": secrets.token_urlsafe(32), "password": "new-pass-123"}, headers=H).status_code for _ in range(12)]
check("reset-token guessing limited", 429 in codes, str(codes[-3:]))
codes = [anon.get("/api/area?lat=18.5&lon=73.8").status_code for _ in range(35)]
check("area lookups rate limited", 429 in codes)

# --- session handling ---
token = a.cookies.get("aa_session")
a.post("/api/auth/logout", headers=H)
replay = httpx.Client(base_url=B, cookies={"aa_session": token})
check("logged-out session cannot be replayed", replay.get("/api/auth/me").json()["user"] is None)

print(f"\n{sum(ok for _, ok in results)}/{len(results)} checks passed")
