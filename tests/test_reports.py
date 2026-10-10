"""The report store contract, run against SQLite and, when AIRAWARE_TEST_MONGO_URL points at a real server, MongoDB.

    docker run -d -p 127.0.0.1:27017:27017 mongo:7
    AIRAWARE_TEST_MONGO_URL=mongodb://127.0.0.1:27017 pytest tests/test_reports.py
"""

import os
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from airaware.server import db, reports

MONGO = os.environ.get("AIRAWARE_TEST_MONGO_URL")
KOTHRUD, AUNDH, BANDRA = (18.5074, 73.8077), (18.5590, 73.8070), (19.0596, 72.8295)


@pytest.fixture(params=["sqlite", "mongodb"])
def store(request, tmp_path, monkeypatch):
    if request.param == "sqlite":
        monkeypatch.setenv("AIRAWARE_DB", str(tmp_path / "reports.db"))
        db.init()
        for uid in (1, 2, 3):
            db.run("INSERT INTO users (id, email, name, pw_hash, created_at) VALUES (?, ?, 'x', 'x', ?)", (uid, f"u{uid}@example.com", db.now()))
        yield reports.SqliteReports()
        return
    if not MONGO:
        pytest.skip("set AIRAWARE_TEST_MONGO_URL to run the MongoDB tests")
    s = reports.MongoReports(MONGO, f"airaware_test_{uuid.uuid4().hex[:8]}")
    yield s
    s.client.drop_database(s.db.name)


def backdate(store, rid: str, when: datetime) -> None:
    if store.backend == "sqlite":
        db.run("UPDATE reports SET created_at = ? WHERE id = ?", (when.isoformat(timespec="seconds"), int(rid)))
    else:
        store.col.update_one({"_id": store._oid(rid)}, {"$set": {"created_at": when}})


def iso(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat(timespec="seconds")


def test_create_read_update_delete(store):
    rid = store.create(1, *KOTHRUD, "Pune", "burning", "smoke behind the market")
    r = store.get(rid)
    assert r["status"] == "pending" and r["kind"] == "burning" and r["user_id"] == 1 and r["city"] == "Pune"
    assert [x["id"] for x in store.find(reports.Filter(user_id=1))] == [rid]
    # The author may correct a pending report; nobody else may.
    assert store.update_own(rid, 1, "construction", "road dust, actually") and store.get(rid)["kind"] == "construction"
    assert not store.update_own(rid, 2, "other", "not mine")
    # Once judged it is fixed for the author, but moderation can still change it.
    assert store.moderate(rid, "approved", 3)
    r = store.get(rid)
    assert r["status"] == "approved" and r["moderated_by"] == 3 and r["moderated_at"]
    assert not store.update_own(rid, 1, "other", "too late")
    assert not store.delete(rid, user_id=2) and store.get(rid)  # someone else's report
    assert store.delete(rid, user_id=1) and store.get(rid) is None
    assert not store.delete(rid)


def test_unknown_and_malformed_ids_are_not_found(store):
    for rid in ("999999", "not-an-id", "", "64b7f1f1f1f1f1f1f1f1f1f1"):
        assert store.get(rid) is None and not store.moderate(rid, "approved", 1) and not store.delete(rid)


def test_filters_by_status_kind_city_and_date(store):
    a = store.create(1, *KOTHRUD, "Pune", "burning", "")
    b = store.create(1, *AUNDH, "Pune", "construction", "")
    c = store.create(2, *BANDRA, "Mumbai", "burning", "")
    backdate(store, a, datetime.now(timezone.utc) - timedelta(days=20))
    store.moderate(b, "approved", 3)
    ids = lambda f: {x["id"] for x in store.find(f)}
    assert ids(reports.Filter()) == {a, b, c}
    assert ids(reports.Filter(status="pending")) == {a, c}
    assert ids(reports.Filter(kind="burning")) == {a, c}
    assert ids(reports.Filter(city="Mumbai")) == {c}
    assert ids(reports.Filter(since=iso(7))) == {b, c}
    assert ids(reports.Filter(until=iso(7))) == {a}
    assert ids(reports.Filter(status="pending", kind="burning", city="Pune")) == {a}
    assert len(store.find(reports.Filter(limit=2))) == 2
    newest_first = [x["id"] for x in store.find(reports.Filter())]
    assert newest_first[-1] == a


def test_near_finds_only_approved_recent_reports_within_the_radius(store):
    close = store.create(1, 18.5100, 73.8100, "Pune", "traffic", "")
    far = store.create(1, *AUNDH, "Pune", "traffic", "")  # about 6 km from Kothrud
    pending = store.create(1, 18.5080, 73.8080, "Pune", "traffic", "")
    old = store.create(1, 18.5075, 73.8075, "Pune", "traffic", "")
    for rid in (close, far, old):
        store.moderate(rid, "approved", 3)
    backdate(store, old, datetime.now(timezone.utc) - timedelta(days=30))
    got = {x["id"] for x in store.near(*KOTHRUD, km=3, since=iso(7))}
    assert got == {close} and pending not in got


def test_statistics_aggregation(store):
    ids = [store.create(1, *KOTHRUD, "Pune", "burning", ""), store.create(1, *KOTHRUD, "Pune", "burning", ""),
           store.create(2, *BANDRA, "Mumbai", "industry", ""), store.create(2, *BANDRA, "Mumbai", "industry", "")]
    for rid in ids:
        backdate(store, rid, datetime.now(timezone.utc) - timedelta(hours=10))
    store.moderate(ids[0], "approved", 3)
    store.moderate(ids[2], "rejected", 3)
    s = store.stats(iso(30))
    assert s["total"] == 4 and s["by_status"] == {"pending": 2, "approved": 1, "rejected": 1}
    pairs = {(x["city"], x["kind"]): (x["n"], x["approved"]) for x in s["by_city_kind"]}
    assert pairs == {("Pune", "burning"): (2, 1), ("Mumbai", "industry"): (2, 0)}
    assert sum(w["n"] for w in s["weekly"]) == 4 and s["moderated"] == 2
    assert 9 < s["median_hours_to_moderate"] < 11
    assert store.counts() == {"total": 4, "pending": 2} and store.per_user() == {1: 2, 2: 2}
    assert store.recent_count(1, iso(1)) == 2 and store.recent_count(1, iso(0.1)) == 0


def test_deleted_account_leaves_reports_without_an_author(store):
    rid = store.create(1, *KOTHRUD, "Pune", "burning", "")
    store.moderate(rid, "approved", 1)
    store.anonymize_user(1)
    assert store.get(rid)["user_id"] is None and store.find(reports.Filter(user_id=1)) == []
    if store.backend == "mongodb":  # the embedded moderation history forgets the author too
        assert all(h.get("by") is None for h in store.col.find_one({"_id": store._oid(rid)})["history"])


def test_mongodb_validator_and_indexes():
    if not MONGO:
        pytest.skip("set AIRAWARE_TEST_MONGO_URL to run the MongoDB tests")
    from pymongo.errors import WriteError
    s = reports.MongoReports(MONGO, f"airaware_test_{uuid.uuid4().hex[:8]}")
    try:
        s.ping()
        names = {i["name"] for i in s.col.list_indexes()}
        assert {"status_city_recent", "location_2dsphere", "by_author", "by_kind"} <= names
        with pytest.raises(WriteError):  # the server itself refuses a document outside the schema
            s.col.insert_one({"lat": 18.5, "lon": 73.8, "city": "Delhi", "kind": "burning", "status": "pending"})
        with pytest.raises(ValueError):  # and the store reports that as a clear validation error
            s.create(1, 18.5, 73.8, "Delhi", "burning", "")
    finally:
        s.client.drop_database(s.db.name)


def test_unreachable_mongodb_fails_fast_and_explicitly():
    s = reports.MongoReports("mongodb://127.0.0.1:1", "nothing_here")
    start = time.monotonic()
    for call in (lambda: s.ping(), lambda: s.find(reports.Filter()), lambda: s.create(1, 18.5, 73.8, "Pune", "burning", ""),
                 lambda: s.counts(), lambda: s.stats(iso(30))):
        with pytest.raises(reports.Unavailable):
            call()
    assert time.monotonic() - start < 20  # a 2-second server-selection timeout each, not a hang
