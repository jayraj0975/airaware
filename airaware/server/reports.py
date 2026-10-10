"""Citizen pollution reports and their moderation.

Stored in MongoDB when AIRAWARE_MONGO_URL is set (the document store: a GeoJSON point with a 2dsphere index for
"reports near here", a schema validator enforced by the server, the moderation history embedded in each report, and
aggregation pipelines for the admin statistics). Without it they stay in the SQLite database, so a deployment without
MongoDB keeps working. Both stores answer the same calls; the API never knows which one it is talking to.

If MongoDB is configured but cannot be reached, every call raises `Unavailable`, which the API turns into a clear
503 for report features only; accounts, forecasts and maps keep working.
"""

import math
import os
import statistics
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from airaware.server import db

KINDS = {"burning": "Garbage or leaf burning", "construction": "Construction or road dust", "industry": "Factory smoke",
         "traffic": "Heavy traffic or idling", "firecrackers": "Firecrackers", "other": "Something else"}
STATUSES = ("pending", "approved", "rejected")
CITIES = ("Pune", "Mumbai")


class Unavailable(Exception):
    """The report database cannot be reached right now."""


@dataclass
class Filter:
    status: str | None = None
    kind: str | None = None
    city: str | None = None
    since: str | None = None  # ISO timestamp, inclusive
    until: str | None = None  # ISO timestamp, exclusive
    user_id: int | None = None
    limit: int = 200


def _utc(iso: str) -> datetime:
    t = datetime.fromisoformat(iso)
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _iso(t: datetime | str | None) -> str | None:
    if t is None or isinstance(t, str):
        return t
    return (t if t.tzinfo else t.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).isoformat(timespec="seconds")


def _median(xs: list[float]) -> float | None:
    return statistics.median(xs) if xs else None


# ---------- SQLite ----------

class SqliteReports:
    backend = "sqlite"
    COLS = "id, user_id, lat, lon, city, kind, note, status, created_at, moderated_by, moderated_at"

    @staticmethod
    def _row(r: dict) -> dict:
        return {**r, "id": str(r["id"])}

    @staticmethod
    def _id(rid: str) -> int | None:
        return int(rid) if str(rid).isdigit() else None

    def ping(self) -> None:
        db.one("SELECT 1 AS ok")

    def create(self, user_id: int, lat: float, lon: float, city: str, kind: str, note: str) -> str:
        return str(db.run("INSERT INTO reports (user_id, lat, lon, city, kind, note, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                          (user_id, lat, lon, city, kind, note, db.now())))

    def recent_count(self, user_id: int, since: str) -> int:
        return db.one("SELECT COUNT(*) AS n FROM reports WHERE user_id = ? AND created_at >= ?", (user_id, since))["n"]

    def find(self, f: Filter) -> list[dict]:
        where, args = [], []
        for col, val in (("status", f.status), ("kind", f.kind), ("city", f.city), ("user_id", f.user_id)):
            if val is not None:
                where.append(f"{col} = ?")
                args.append(val)
        if f.since:
            where.append("created_at >= ?")
            args.append(_iso(_utc(f.since)))
        if f.until:
            where.append("created_at < ?")
            args.append(_iso(_utc(f.until)))
        sql = f"SELECT {self.COLS} FROM reports {'WHERE ' + ' AND '.join(where) if where else ''} ORDER BY created_at DESC, id DESC LIMIT ?"
        return [self._row(r) for r in db.rows(sql, (*args, f.limit))]

    def near(self, lat: float, lon: float, km: float, since: str, limit: int = 50) -> list[dict]:
        # A bounding box first (indexed), then the exact great-circle distance.
        dlat, dlon = km / 111.0, km / (111.0 * max(math.cos(math.radians(lat)), 0.01))
        rows = db.rows(f"""SELECT {self.COLS} FROM reports WHERE status = 'approved' AND created_at >= ?
                           AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ? ORDER BY created_at DESC""",
                       (since, lat - dlat, lat + dlat, lon - dlon, lon + dlon))
        return [self._row(r) for r in rows if _km(lat, lon, r["lat"], r["lon"]) <= km][:limit]

    def get(self, rid: str) -> dict | None:
        i = self._id(rid)
        r = db.one(f"SELECT {self.COLS} FROM reports WHERE id = ?", (i,)) if i is not None else None
        return self._row(r) if r else None

    def update_own(self, rid: str, user_id: int, kind: str, note: str) -> bool:
        i = self._id(rid)
        return i is not None and bool(db.run("UPDATE reports SET kind = ?, note = ? WHERE id = ? AND user_id = ? AND status = 'pending'",
                                             (kind, note, i, user_id)))

    def moderate(self, rid: str, status: str, admin_id: int) -> bool:
        i = self._id(rid)
        return i is not None and bool(db.run("UPDATE reports SET status = ?, moderated_by = ?, moderated_at = ? WHERE id = ?",
                                             (status, admin_id, db.now(), i)))

    def delete(self, rid: str, user_id: int | None = None) -> bool:
        i = self._id(rid)
        if i is None:
            return False
        if user_id is None:
            return bool(db.run("DELETE FROM reports WHERE id = ?", (i,)))
        return bool(db.run("DELETE FROM reports WHERE id = ? AND user_id = ?", (i, user_id)))

    def anonymize_user(self, user_id: int) -> None:
        db.run("UPDATE reports SET user_id = NULL WHERE user_id = ?", (user_id,))

    def counts(self) -> dict:
        r = db.one("SELECT COUNT(*) AS total, SUM(status = 'pending') AS pending FROM reports")
        return {"total": r["total"], "pending": r["pending"] or 0}

    def per_user(self) -> dict[int, int]:
        return {r["user_id"]: r["n"] for r in db.rows("SELECT user_id, COUNT(*) AS n FROM reports WHERE user_id IS NOT NULL GROUP BY user_id")}

    def stats(self, since: str) -> dict:
        rows = db.rows("SELECT city, kind, status, created_at, moderated_at FROM reports WHERE created_at >= ?", (since,))
        return _summarise(rows)


# ---------- MongoDB ----------

VALIDATOR = {"$jsonSchema": {
    "bsonType": "object",
    "required": ["location", "lat", "lon", "city", "kind", "note", "status", "created_at", "history"],
    "properties": {
        "user_id": {"bsonType": ["int", "long", "null"]},
        "location": {"bsonType": "object", "required": ["type", "coordinates"],
                     "properties": {"type": {"enum": ["Point"]}, "coordinates": {"bsonType": "array", "minItems": 2, "maxItems": 2}}},
        "lat": {"bsonType": "double", "minimum": -90, "maximum": 90},
        "lon": {"bsonType": "double", "minimum": -180, "maximum": 180},
        "city": {"enum": list(CITIES)},
        "kind": {"enum": list(KINDS)},
        "note": {"bsonType": "string", "maxLength": 280},
        "status": {"enum": list(STATUSES)},
        "created_at": {"bsonType": "date"},
        "moderated_by": {"bsonType": ["int", "long", "null"]},
        "moderated_at": {"bsonType": ["date", "null"]},
        "history": {"bsonType": "array", "items": {"bsonType": "object", "required": ["status", "at"]}},
    },
}}


def _mongo_errors(fn):
    """Any driver error (server down, timeout, refused write) becomes Unavailable or a clear ValueError."""
    def wrapped(self, *a, **k):
        from pymongo.errors import ConnectionFailure, OperationFailure, PyMongoError, WriteError
        try:
            return fn(self, *a, **k)
        except (ConnectionFailure,) as e:
            raise Unavailable("The report database cannot be reached.") from e
        except WriteError as e:  # the server-side schema validator refused the document
            raise ValueError("The report was refused by the database's validation rules.") from e
        except (OperationFailure, PyMongoError) as e:
            raise Unavailable("The report database returned an error.") from e
    wrapped.__name__, wrapped.__doc__ = fn.__name__, fn.__doc__
    return wrapped


class MongoReports:
    backend = "mongodb"

    def __init__(self, url: str, name: str = "airaware"):
        from pymongo import MongoClient
        # Short timeouts: when the database is down, report pages say so in two seconds instead of hanging.
        self.client = MongoClient(url, serverSelectionTimeoutMS=2000, connectTimeoutMS=2000, socketTimeoutMS=5000,
                                  tz_aware=True, appname="airaware")
        self.db = self.client[name]
        self.col = self.db["reports"]
        self._ready = False
        self._lock = threading.Lock()

    def _setup(self) -> None:
        """Collection with its validator, and the indexes the queries use. Idempotent; runs on first use."""
        if self._ready:
            return
        with self._lock:
            if self._ready:
                return
            if "reports" in self.db.list_collection_names():
                self.db.command("collMod", "reports", validator=VALIDATOR, validationLevel="strict")
            else:
                self.db.create_collection("reports", validator=VALIDATOR, validationLevel="strict")
            self.col.create_index([("status", 1), ("city", 1), ("created_at", -1)], name="status_city_recent")
            self.col.create_index([("location", "2dsphere")], name="location_2dsphere")
            self.col.create_index([("user_id", 1), ("created_at", -1)], name="by_author")
            self.col.create_index([("kind", 1), ("created_at", -1)], name="by_kind")
            self._ready = True

    @staticmethod
    def _oid(rid: str):
        from bson import ObjectId
        from bson.errors import InvalidId
        try:
            return ObjectId(str(rid))
        except (InvalidId, TypeError):
            return None

    @staticmethod
    def _row(d: dict) -> dict:
        return {"id": str(d["_id"]), "user_id": d.get("user_id"), "lat": d["lat"], "lon": d["lon"], "city": d["city"],
                "kind": d["kind"], "note": d["note"], "status": d["status"], "created_at": _iso(d["created_at"]),
                "moderated_by": d.get("moderated_by"), "moderated_at": _iso(d.get("moderated_at"))}

    @_mongo_errors
    def ping(self) -> None:
        self.client.admin.command("ping")
        self._setup()

    @_mongo_errors
    def create(self, user_id: int, lat: float, lon: float, city: str, kind: str, note: str) -> str:
        self._setup()
        now = datetime.now(timezone.utc)
        doc = {"user_id": user_id, "location": {"type": "Point", "coordinates": [float(lon), float(lat)]},
               "lat": float(lat), "lon": float(lon), "city": city, "kind": kind, "note": note, "status": "pending",
               "created_at": now, "moderated_by": None, "moderated_at": None,
               "history": [{"status": "pending", "by": user_id, "at": now}]}
        return str(self.col.insert_one(doc).inserted_id)

    @_mongo_errors
    def recent_count(self, user_id: int, since: str) -> int:
        self._setup()
        return self.col.count_documents({"user_id": user_id, "created_at": {"$gte": _utc(since)}})

    @_mongo_errors
    def find(self, f: Filter) -> list[dict]:
        self._setup()
        q: dict = {k: v for k, v in (("status", f.status), ("kind", f.kind), ("city", f.city), ("user_id", f.user_id)) if v is not None}
        when = {**({"$gte": _utc(f.since)} if f.since else {}), **({"$lt": _utc(f.until)} if f.until else {})}
        if when:
            q["created_at"] = when
        return [self._row(d) for d in self.col.find(q).sort([("created_at", -1), ("_id", -1)]).limit(f.limit)]

    @_mongo_errors
    def near(self, lat: float, lon: float, km: float, since: str, limit: int = 50) -> list[dict]:
        self._setup()
        q = {"status": "approved", "created_at": {"$gte": _utc(since)},
             "location": {"$nearSphere": {"$geometry": {"type": "Point", "coordinates": [float(lon), float(lat)]},
                                          "$maxDistance": km * 1000}}}
        return [self._row(d) for d in self.col.find(q).limit(limit)]

    @_mongo_errors
    def get(self, rid: str) -> dict | None:
        self._setup()
        oid = self._oid(rid)
        d = self.col.find_one({"_id": oid}) if oid else None
        return self._row(d) if d else None

    @_mongo_errors
    def update_own(self, rid: str, user_id: int, kind: str, note: str) -> bool:
        self._setup()
        oid = self._oid(rid)
        return bool(oid) and self.col.update_one({"_id": oid, "user_id": user_id, "status": "pending"},
                                                 {"$set": {"kind": kind, "note": note}}).matched_count == 1

    @_mongo_errors
    def moderate(self, rid: str, status: str, admin_id: int) -> bool:
        self._setup()
        oid = self._oid(rid)
        if not oid:
            return False
        now = datetime.now(timezone.utc)
        r = self.col.update_one({"_id": oid}, {"$set": {"status": status, "moderated_by": admin_id, "moderated_at": now},
                                               "$push": {"history": {"status": status, "by": admin_id, "at": now}}})
        return r.matched_count == 1

    @_mongo_errors
    def delete(self, rid: str, user_id: int | None = None) -> bool:
        self._setup()
        oid = self._oid(rid)
        if not oid:
            return False
        return self.col.delete_one({"_id": oid, **({"user_id": user_id} if user_id is not None else {})}).deleted_count == 1

    @_mongo_errors
    def anonymize_user(self, user_id: int) -> None:
        """Account deleted: its reports stay public information, without the author (as in SQLite's ON DELETE SET NULL)."""
        self._setup()
        self.col.update_many({"user_id": user_id}, {"$set": {"user_id": None, "history.$[h].by": None}},
                             array_filters=[{"h.by": user_id}])

    @_mongo_errors
    def counts(self) -> dict:
        self._setup()
        return {"total": self.col.count_documents({}), "pending": self.col.count_documents({"status": "pending"})}

    @_mongo_errors
    def per_user(self) -> dict[int, int]:
        self._setup()
        return {d["_id"]: d["n"] for d in self.col.aggregate([
            {"$match": {"user_id": {"$ne": None}}}, {"$group": {"_id": "$user_id", "n": {"$sum": 1}}}])}

    @_mongo_errors
    def stats(self, since: str) -> dict:
        """One aggregation with four facets: status counts, city x kind, the weekly trend, and moderation turnaround."""
        self._setup()
        [out] = self.col.aggregate([
            {"$match": {"created_at": {"$gte": _utc(since)}}},
            {"$facet": {
                "by_status": [{"$group": {"_id": "$status", "n": {"$sum": 1}}}],
                "by_city_kind": [{"$group": {"_id": {"city": "$city", "kind": "$kind"}, "n": {"$sum": 1},
                                             "approved": {"$sum": {"$cond": [{"$eq": ["$status", "approved"]}, 1, 0]}}}},
                                 {"$sort": {"n": -1}}],
                "weekly": [{"$group": {"_id": {"$dateTrunc": {"date": "$created_at", "unit": "week", "startOfWeek": "monday"}},
                                       "n": {"$sum": 1}}}, {"$sort": {"_id": 1}}],
                "turnaround": [{"$match": {"moderated_at": {"$ne": None}}},
                               {"$project": {"hours": {"$divide": [{"$subtract": ["$moderated_at", "$created_at"]}, 3_600_000]}}},
                               {"$group": {"_id": None, "median": {"$median": {"input": "$hours", "method": "approximate"}},
                                           "n": {"$sum": 1}}}],
            }},
        ])
        turn = out["turnaround"][0] if out["turnaround"] else {"median": None, "n": 0}
        return {
            "total": sum(x["n"] for x in out["by_status"]),
            "by_status": {s: next((x["n"] for x in out["by_status"] if x["_id"] == s), 0) for s in STATUSES},
            "by_city_kind": [{"city": x["_id"]["city"], "kind": x["_id"]["kind"], "n": x["n"], "approved": x["approved"]} for x in out["by_city_kind"]],
            "weekly": [{"week": x["_id"].date().isoformat(), "n": x["n"]} for x in out["weekly"]],
            "median_hours_to_moderate": turn["median"], "moderated": turn["n"],
        }


# ---------- shared ----------

def _km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(a))


def _summarise(rows: list[dict]) -> dict:
    """The same statistics as the MongoDB aggregation, computed in Python for the SQLite store."""
    by_ck: dict[tuple, dict] = {}
    weekly: dict[str, int] = {}
    hours = []
    for r in rows:
        k = by_ck.setdefault((r["city"], r["kind"]), {"city": r["city"], "kind": r["kind"], "n": 0, "approved": 0})
        k["n"] += 1
        k["approved"] += r["status"] == "approved"
        t = _utc(r["created_at"])
        monday = (t - timedelta(days=t.weekday())).date().isoformat()
        weekly[monday] = weekly.get(monday, 0) + 1
        if r["moderated_at"]:
            hours.append((_utc(r["moderated_at"]) - t).total_seconds() / 3600)
    return {"total": len(rows), "by_status": {s: sum(r["status"] == s for r in rows) for s in STATUSES},
            "by_city_kind": sorted(by_ck.values(), key=lambda x: -x["n"]),
            "weekly": [{"week": w, "n": n} for w, n in sorted(weekly.items())],
            "median_hours_to_moderate": _median(hours), "moderated": len(hours)}


_store = None
_store_lock = threading.Lock()


def store():
    """The configured report store (created once). AIRAWARE_MONGO_URL selects MongoDB; otherwise SQLite."""
    global _store
    url = os.environ.get("AIRAWARE_MONGO_URL", "").strip()
    with _store_lock:
        if _store is None or getattr(_store, "url", "") != url:
            _store = MongoReports(url, os.environ.get("AIRAWARE_MONGO_DB", "airaware")) if url else SqliteReports()
            _store.url = url
    return _store


def describe() -> dict:
    """Which store is in use and whether it answers, for the admin console."""
    s = store()
    try:
        s.ping()
        return {"backend": s.backend, "ok": True}
    except Unavailable as e:
        return {"backend": s.backend, "ok": False, "error": str(e)}
