# Databases in AirAware

AirAware uses two databases, each for the data it suits:

| Data | Store | Why |
|---|---|---|
| Accounts, sessions, saved places, alerts, notifications, privacy requests, forecast log, audit trail, rate limits | **SQLite** (`airaware/server/db.py`) | Small, relational, needs transactions and foreign keys (deleting a user cascades to their places and sessions); one file, backed up daily |
| **Citizen pollution reports and their moderation** | **MongoDB** when `AIRAWARE_MONGO_URL` is set (`airaware/server/reports.py`), otherwise SQLite | Each report is a self-contained document with a location and a growing moderation history; queries are geographic ("reports within 3 km") and analytical (counts by city, kind, week) |

Without `AIRAWARE_MONGO_URL` the same report features run on SQLite, so a host without MongoDB (the Railway
deployment) keeps working. The API code calls one interface and never knows which store answers.

## The report document

```js
{
  _id: ObjectId("6aca0e0e7f106e43af357de4"),
  user_id: 12,                                  // the author's account id in SQLite; null once the account is deleted
  location: { type: "Point", coordinates: [73.8077, 18.5074] },   // GeoJSON: longitude first
  lat: 18.5074, lon: 73.8077,
  city: "Pune",                                 // Pune | Mumbai
  kind: "burning",                              // burning | construction | industry | traffic | firecrackers | other
  note: "Leaf burning behind the society every evening",           // up to 280 characters
  status: "approved",                           // pending | approved | rejected
  created_at: ISODate("2026-10-10T10:06:06Z"),
  moderated_by: 3, moderated_at: ISODate("2026-10-10T10:20:00Z"),
  history: [                                    // embedded: every decision, in order
    { status: "pending",  by: 12, at: ISODate("2026-10-10T10:06:06Z") },
    { status: "approved", by: 3,  at: ISODate("2026-10-10T10:20:00Z") }
  ]
}
```

**Server-side validation.** The collection is created with a `$jsonSchema` validator (`validationLevel: strict`):
required fields, the allowed cities, kinds and statuses, the coordinate ranges and the 280-character note limit.
MongoDB itself refuses a document that breaks these rules, even one written outside the app. The API validates
first (Pydantic), so users see a clear message; the validator is the second line of defence.

**Indexes**, and the query each one serves:

| Index | Serves |
|---|---|
| `{status: 1, city: 1, created_at: -1}` | the public map (approved reports in a city, newest first) and the moderation queue |
| `{location: "2dsphere"}` | `$nearSphere`: approved reports within 3 km of a clicked spot |
| `{user_id: 1, created_at: -1}` | "your reports", the data export, the hourly limit, anonymising on account deletion |
| `{kind: 1, created_at: -1}` | filtering the queue by kind |

## Operations

| Operation | Endpoint | Who | MongoDB call |
|---|---|---|---|
| Create | `POST /api/reports` | signed-in user (10 per hour) | `insert_one` |
| Read: public map | `GET /api/reports?city=` | anyone; approved only, never the author | `find` + sort + limit |
| Read: near a spot | inside `GET /api/area` | anyone | `find` with `$nearSphere` |
| Read: your own | `GET /api/me/reports` | the author | `find({user_id})` |
| Read: moderation queue | `GET /api/admin/reports?status=&kind=&city=&since=&until=` | admin | `find` with filters |
| Update: correct a pending report | `PATCH /api/me/reports/{id}` | the author, while pending | `update_one` |
| Update: moderate | `PATCH /api/admin/reports/{id}` | admin | `update_one` with `$set` + `$push` to `history` |
| Delete: withdraw | `DELETE /api/me/reports/{id}` | the author | `delete_one` |
| Delete: remove spam | `DELETE /api/admin/reports/{id}` | admin | `delete_one` |
| Statistics | `GET /api/admin/reports/stats?days=` | admin | one `aggregate` with `$facet` |
| Account deleted | inside `DELETE /api/me` | the user | `update_many` with an array filter on `history` |

**The aggregation** (`MongoReports.stats`): `$match` on the period, then `$facet` computes four results in one pass:
counts by status (`$group`), reports and approvals by city and kind (`$group` with `$cond`), a weekly trend
(`$dateTrunc` to Monday-starting weeks) and the median time to moderate (`$subtract` of two dates, `$median`). The
admin console shows them under "Reports, last 90 days".

**Access control** is enforced in the API, not the database: sign-in for creating, the author's id in the filter for
editing and withdrawing (so another user's id simply matches nothing), and the admin role plus two-step sign-in for
moderation and statistics. The public listing never returns `user_id`.

**When MongoDB is down.** The client uses two-second timeouts. Every report call then raises `Unavailable`, which the
API turns into a 503 with a plain message. Forecasts, maps, accounts and alerts keep working; the area panel shows
"reports unavailable"; the admin console shows the store as offline. The data export and account deletion refuse to
run rather than silently skipping the reports (an export must be complete, and a deletion must anonymise them).

## Setting it up

**Local development**

```sh
docker run -d --name airaware-mongo -p 127.0.0.1:27017:27017 -v airaware-mongo:/data/db mongo:7
AIRAWARE_MONGO_URL=mongodb://127.0.0.1:27017 .venv/bin/uvicorn airaware.server.app:app --port 8000
```

The collection, its validator and its indexes are created on first use. Inspect them with
`docker exec -it airaware-mongo mongosh airaware --eval 'db.reports.getIndexes()'`.

**With Docker Compose** (MongoDB on the private network, no published port):

```sh
# in .env
AIRAWARE_MONGO_URL=mongodb://172.30.0.30:27017
docker compose --profile mongo up -d
```

To require a login, set `MONGO_ROOT_USER` and `MONGO_ROOT_PASSWORD` in `.env` before the first start and use
`mongodb://USER:PASSWORD@172.30.0.30:27017/?authSource=admin`.

**Tests** (`tests/test_reports.py` runs the same contract on both stores; `tests/test_web.py` covers the API):

```sh
AIRAWARE_TEST_MONGO_URL=mongodb://127.0.0.1:27017 .venv/bin/python -m pytest tests/test_reports.py tests/test_web.py
```

Without `AIRAWARE_TEST_MONGO_URL` the MongoDB tests are skipped and reported as such. CI runs them against a
`mongo:7` service container.

## Mapping to the AD mini-project requirement

**What was available.** The only syllabus document found with the project files is the Second Year B.Tech IT
*Skill Enhancement Lab* (ITE05251) syllabus, which asks for a group mini project with a GUI, object-oriented design and
file-based storage. The AD course syllabus itself was **not** found. The requirement used here is the one stated in the
project brief: a GUI application backed by MongoDB, Cassandra, a vector database or a graph database.

| Stated requirement | How AirAware meets it |
|---|---|
| A GUI application | The React web interface: citizens report and manage their reports on the map and dashboard; admins filter, moderate, delete and see statistics in the admin console |
| Backed by MongoDB (one of the allowed databases) | Pollution reports and moderation persist in a real MongoDB collection (not a mock or an in-memory copy) |
| Database operations | Create, read (with filters by status, kind, city and date), update, delete, a geospatial query, and an aggregation pipeline |
| Schema and indexing | A server-enforced `$jsonSchema` validator and four indexes chosen for the actual queries, including a 2dsphere index |
| Reliability | Explicit behaviour when the database is unreachable; tests against a real server, locally and in CI |

**To confirm with the faculty before submission:**

- the AD syllabus's exact requirements (a specific list of operations, replication or sharding, a required report format);
- whether a web GUI is acceptable or a desktop GUI is expected;
- whether a hybrid design (SQLite for accounts, MongoDB for reports) satisfies "backed by MongoDB", or whether more of
  the data must live in MongoDB;
- whether one project may be submitted for both the DSML and the AD mini projects. That is the department's decision;
  nothing here guarantees it will be accepted.
