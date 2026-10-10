# AirAware

**Know your air, a week ahead.** A full-stack platform that forecasts air quality for any street in **Pune** and
**Mumbai** up to seven days ahead, from 37 government (CPCB) monitoring stations and the weather forecast. People sign up to save their places, get advice tuned to their health and an alert before a bad
day, and report pollution sources; admins moderate reports, manage users and watch the data pipeline.

**Live: [airaware-production-8299.up.railway.app](https://airaware-production-8299.up.railway.app)** · installable on a phone as an app.

DS/ML mini project (fits *Weather Data Analysis and Prediction System*) built as a portfolio product.

| Honest test (inputs available on the day), 662 next-day forecasts | |
|---|---|
| Next-day error | **12.0 AQI** vs 12.4 for "tomorrow = today" (3% lower; not statistically significant, p = 0.20) |
| 5 days ahead | **20.7** vs 25.3 (18% lower; Diebold-Mariano p = 0.003) |
| Where the gain is significant | 4 to 7 days ahead (p < 0.05) |
| 80% forecast ranges | held the real AQI 78-88% of the time across horizons |

![Today: the forecast, today hour by hour, and any area on the map](docs/screenshots/home.png)

| Insights | Science |
|---|---|
| ![When the air is cleanest, the Diwali effect, the year in air](docs/screenshots/insights.png) | ![The model against baselines, error by horizon, what it relies on](docs/screenshots/science.png) |
| **Your dashboard** | **Admin console** |
| ![Saved places with forecasts, alerts and personal advice](docs/screenshots/dashboard.png) | ![Users, alerts, reports, forecast log and data freshness](docs/screenshots/admin.png) |

<p align="center"><img src="docs/screenshots/mobile.png" width="260" alt="On a phone, installable as an app"></p>

## Features

**For everyone**
- **Today**: the forecast for today and tomorrow with an 80% range, the chance of a Poor day and health advice;
  the cleanest day and hours ahead; weather now; six weeks of history joined to the week ahead.
- **Any area**: click anywhere (or use your location) for that spot's estimated AQI, its forecast, the weather there
  now, the nearest stations and pollution reported nearby.
- **Compare**: up to four spots (home, office, school) side by side for the week.
- **Insights**: the hour-by-month heatmap of when the air is cleanest, the Diwali effect, the year in air, weekdays,
  the past year in cigarettes.
- **Science**: the model against baselines, error by horizon, what the model relies on, and the method.
- **Track record**: every forecast the site publishes is logged before its day and scored against the real AQI once
  the stations report it.
- **Today, hour by hour**: the day's forecast spread over the city's usual daily pattern, with the cleanest hours.
- **Installable app**: add it to a phone's home screen; it opens offline with the last public forecast it saw.

**With an account**
- Saved places with their own forecasts, and **alerts** at a chosen AQI, raised once per day in the app (and by
  email when SMTP is configured).
- A **health profile** (asthma, heart disease, children, over 65, pregnancy, outdoor work): advice and warning levels
  across the site adapt to it, warning sensitive groups one category earlier.
- **Report pollution** (garbage burning, construction dust, factory smoke…) on the map; shown publicly once approved.
- Change password (signs out other devices), reset a forgotten one, delete the account and its data.

**Admin console**
- Overview: users, active users, places, alerts, warnings sent, reports waiting, forecasts logged and scored,
  model error, data freshness per city, sign-ups over 30 days.
- Users: search, promote or demote admins, disable accounts (ends their sessions), issue a one-time password-reset
  link to pass to someone who cannot get email.
- Reports: moderation queue on a map, approve or reject.
- Data & jobs: every startup, scheduled and manual rebuild with its result; **Rebuild data now**; the health of each
  station (days reporting, agreement with its city).
- Backups: the database is copied every day to `data/backups/` (the newest 7 are kept), and admins can download a
  fresh copy (`POST /api/admin/backup`, audited).
- Audit log: sign-ups, sign-ins, failed sign-ins, admin actions.

## Architecture

```
 Browser ── React 19 + TypeScript (Vite) ─ Leaflet map, Chart.js
    │ JSON over /api, session cookie
 FastAPI (airaware/server) ─┬─ public.py   overview, stations, any area, model, insights, track record, reports
                            ├─ account.py  sign-up/in, profile, places, alerts, notifications
                            ├─ admin.py    overview, users, moderation, jobs, audit
                            ├─ core.py     state, forecast log + scoring, alerts, background refresh
                            ├─ reports.py  citizen reports + moderation: MongoDB when AIRAWARE_MONGO_URL is set
                            │              (2dsphere index, $jsonSchema validator, aggregation), else SQLite
                            └─ db.py       SQLite (WAL): users, sessions, places, alerts, notifications,
                                           forecast_log, jobs, audit
 ML and data (airaware/) ── data.py (download + clean), model.py (walk-forward ridge models, conformal ranges,
                            Diebold-Mariano), insights.py, live.py (weather, any-point estimates, OpenAQ)
 Sources ── OpenAQ archive of CPCB stations · Open-Meteo (ERA5, forecasts, archived forecast runs, CAMS) · OpenStreetMap
```

**Two applications, two roles.** The React + FastAPI platform above is the product: it is what Docker and the
deployment run. `app.py` is a separate **Streamlit analysis app** for the data-science side (replay any test day,
what-if weather sliders, exact per-forecast explanations, error by month). It reads the same data and models but is
not deployed; run it locally with `.venv/bin/streamlit run app.py`.

**Databases.** Accounts and everything relational live in SQLite; pollution reports live in MongoDB when it is
configured. Why, the document schema, indexes, the aggregation pipeline, setup and the AD mini-project mapping are in
**[docs/DATABASE.md](docs/DATABASE.md)**.

A background thread rebuilds the data and retrains every 6 hours (live readings hourly with an OpenAQ key), logs
the new forecasts, scores old ones whose day has been measured, and raises alerts.

**Privacy and the DPDP Act 2023**
- Plain-language [Privacy Notice](frontend/src/pages/Legal.tsx) and Terms; sign-up records agreement and an 18+
  confirmation, and asks again when the policy version changes.
- Health information needs separate, explicit consent; withdrawing it erases it at once.
- Rights in the dashboard: download everything (JSON with purposes), correct, erase (delete account). Anyone can file
  a privacy request or grievance; admins answer them from an inbox that shows their age.
- Retention limits applied daily; one strictly necessary cookie; no analytics or tracking; no access log, so looked-up
  locations are never stored next to IP addresses.

**Security**
- Passwords hashed with scrypt.
- Sessions in HttpOnly SameSite cookies; only a hash of each token is stored. Sessions are cleared on logout,
  password change and disable.
- Every write needs an `X-AirAware` header, which blocks cross-site requests.
- Limits, counted in the database with an atomic check-and-record so parallel requests cannot slip past: sign-in
  attempts (10 per 15 minutes per email, 20 per IPv4 address or IPv6 /64), sign-ups (5 an hour per network). Area
  lookups are limited per visitor (30 a minute) and calls to outside services are rate-capped.
- Admins are made only from the server command line, never by signing up with a particular email, and must turn on
  two-step sign-in (TOTP authenticator codes, replay-protected) before the admin console opens.
- Self-pentest: `security/attack.py` runs 69 attacks (CSRF, CORS, IDOR on places, alerts and reports, admin access, SQL and operator injection, XSS storage, Host-header injection,
  NaN/huge inputs, 64 kB body cap, path traversal, brute force, reset-token guessing, rate limits, session replay)
  and runs in CI with pip-audit and npm audit on every push.
- Behind the tunnel, a visitor's real address is taken only from the trusted proxy, so limits work per visitor and
  the forwarding headers cannot be forged; HSTS is sent over HTTPS; the Server header does not name the software.
- Password resets: one-time links (an hour by email, a day from an admin), stored only as hashes, voided by a newer
  link, and carried after `#` so they never reach server logs. "Forgot password" answers the same, in the same time,
  whether or not the email has an account (the work happens after the reply). Emailed links use AIRAWARE_PUBLIC_URL,
  never the request's Host header. Changing a password or disabling an account voids outstanding links and sessions.
- Re-entering a password for a sensitive change (new password, account deletion) is capped at 5 tries per 15 minutes
  per account, since each check is a deliberately expensive scrypt hash.
- Security headers (CSP, frame denial, nosniff).
- Per-user ownership checks on every place, alert and notification. The container runs as a non-root user.

## Run it

Everything about running and hosting AirAware is in **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)**: requirements,
the one recommended public setup (a small server running `compose.yaml` behind a named Cloudflare Tunnel), every
setting, backups and troubleshooting. In short:

```sh
cp .env.example .env                    # optional settings; never commit .env
docker compose up -d                    # http://localhost:8000
docker compose --profile quick up -d    # plus a temporary public HTTPS address, for laptop demos
docker compose --profile mongo up -d    # plus MongoDB for pollution reports (set AIRAWARE_MONGO_URL, see docs/DATABASE.md)
docker compose down                     # stop; data stays in the airaware-data volume
```

After signing up, make yourself an admin from the machine running it (the only way: the site never grants admin on
sign-up, because it does not verify email ownership), then turn on two-step sign-in to open the admin console:
`docker compose exec airaware python -m airaware.server.manage make-admin you@example.com`.

**Development:**

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn airaware.server.app:app --reload --port 8000     # API (+ built frontend)
cd frontend && npm ci && npm run dev                               # http://localhost:5173, proxies /api
.venv/bin/python -m pytest                                         # 65 backend tests (8 need MongoDB: set
                                                                   #   AIRAWARE_TEST_MONGO_URL, else they are skipped)
cd frontend && npm run build && npx playwright test                # 36 browser tests, desktop and phone
```

API docs (OpenAPI): http://localhost:8000/api/docs.

**CI** (GitHub Actions, every push): backend tests, frontend lint and type-checked build, end-to-end browser tests
on desktop and phone sizes, and a Docker build that is started and smoke-tested.

Other tools: `.venv/bin/streamlit run app.py` (the analysis app), `python -m airaware.model` (re-run the evaluation
into reports/metrics.md), `python -m airaware.data` (refresh the station, weather and CAMS data) and
`python -m airaware.data --vintage` (refresh the archive of issued weather forecasts).

## Data

- **Air quality**: CPCB continuous monitoring stations (14 in Pune including Pimpri-Chinchwad, 23 in Mumbai; Navi Mumbai and Vasai excluded),
  15-minute readings from [OpenAQ's public archive](https://openaq.org) (`openaq-data-archive` on AWS, no account needed).
- **Weather**: ERA5 reanalysis from [Open-Meteo](https://open-meteo.com) (no key): temperature, humidity, rain, wind,
  pressure and boundary-layer (mixing) height at each city centre. Open-Meteo's forecast fills the last few days ERA5
  has not reached yet and the week ahead. Current conditions come from Open-Meteo's live forecast API.
- **Issued weather forecasts**: Open-Meteo's archive of past forecast runs (June 2024 onwards), the weather as it was
  forecast 1 to 7 days before each day. This is what makes a fair backtest possible (see Method).
- **CAMS**: the Copernicus Atmosphere Monitoring Service PM2.5 and PM10, through Open-Meteo (no key): its analysis for
  every day since August 2022 and its forecast for the next four days. CAMS reads 2-4× low in Indian cities because
  it misses local road dust, but it rises and falls with the stations (correlation 0.88 in Pune). Its past forecasts are
  not archived, so it is only used in the upper-bound experiment, not by the served model. On its own, even scaled to the stations, it was a worse live estimate than the four-day-old reading (Pune MAE
  24 vs 16), so the site does not show it as a live AQI.

### Cleaning (`airaware/data.py`)

Raw station data is messy, and the cleaning is part of the project:

1. Drop zero, negative, and 985/999 readings (instrument error codes).
2. Drop a sensor stuck on the same value for two hours or more.
3. Drop readings where PM2.5 exceeds PM10. PM2.5 is part of PM10, so that pair is impossible.
4. Hourly means → a daily value only if the station has **16 or more valid hours** (CPCB's rule).
5. Station AQI = the worse of the PM2.5 and PM10 sub-indices (CPCB breakpoints, `airaware/aqi.py`).
6. City AQI = the mean of the stations that reported, kept only if **at least two** reported.
7. OpenAQ re-listed many stations under new ids in February 2025, so a station's old and new ids are merged by name.

**Why only PM2.5 and PM10?** They set the AQI on almost every day in these two cities. The archived gas readings
are not reliable enough to use: their units are mislabelled (CO in mg/m³ marked as ppb) and some values are
impossible (ozone below 1 µg/m³).

**Coverage.** The archive is nearly empty for 2023–2024 and sparse before 2025. Dense data runs from
February 2025 to October 2026. That gives about 1,460 city-days with an AQI.

## Method

Each row is one city on one evening D; the target is the AQI on D+h for h = 1 to 7 days. The rule that matters most:
**every input must be something a forecaster really had on the evening of D.** Weather records (ERA5) and the CAMS particle
analysis are only known afterwards and are more accurate than the forecasts available on the day, so a backtest fed with
them looks better than the model can ever be live.

Three models are compared on exactly the same test rows (`airaware/model.py`):

- **AirAware**, the model the site serves: the stations' history (today's AQI, PM2.5 and PM10, the two days before, the
  7-day mean), the calendar (season, weekday, Diwali week), the city, and **weather as it was actually forecast**. The
  forecasts come from Open-Meteo's archive of past runs (`python -m airaware.data --vintage` writes
  `data/forecast_vintage.csv`, June 2024 onwards): today's weather from the run issued a day earlier, and the target day's
  weather from runs issued h + 1 days before it, so every run was issued before D. Seven days ahead no archived run is old
  enough, so AirAware uses station history only there. Boundary-layer height is not in the archive.
- **Station history only**: the same station and calendar inputs with no weather and no CAMS at all. This is the most
  conservative benchmark: nothing in it can be more accurate in the backtest than it was on the day.
- **Upper bound**: the original design, with the realized weather and the CAMS analysis for the target day. CAMS keeps no
  archive of its past forecasts, so this cannot be made fair. It is kept only to show what perfect weather and particle
  forecasts would add. It is **not** an estimate of live accuracy.

AQI changes slowly from day to day, so a model that predicts the AQI level directly loses to simply saying
"tomorrow = today". All three predict the **change** from today with ridge (linear) regression, one model per horizon.
At run time AirAware is given the best weather known at that moment (ERA5 for past days, the current forecast ahead): never
anything from the future, only fresher than the archived runs it was trained on.

**Walk-forward evaluation.** At the start of each month from October 2025, every method is retrained on the rows whose
target had already been measured by that day, then forecasts the month. Next day: 662 city-day forecasts for
2 October 2025 to 6 October 2026, including winter 2025–26. Tests in `tests/test_airaware.py` check that training targets
were measured before each forecast, that no feature changes when any later AQI changes, that issued-forecast columns come
from runs issued before D, that the conservative benchmark ignores weather and CAMS, and that every method is scored on the
same rows, reproducibly and with missing data.

Reproduce: `python -m airaware.model` (writes [`reports/metrics.md`](reports/metrics.md)).

| Method (next day) | MAE | RMSE | R² | Category accuracy | Poor-day recall |
|---|---:|---:|---:|---:|---:|
| Persistence (tomorrow = today) | 12.42 | 18.09 | 0.864 | 76.7% | **61.5%** |
| 7-day average | 17.93 | 25.48 | 0.730 | 66.5% | 11.5% |
| Seasonal average (city, month) | 28.84 | 40.02 | 0.333 | 56.5% | 0% |
| Station history only (no weather, no CAMS) | 12.11 | 17.42 | 0.874 | 77.2% | 53.8% |
| Linear regression on the AQI level (AirAware's inputs) | 12.37 | 17.53 | 0.872 | 77.2% | 34.6% |
| Gradient boosting on the change (AirAware's inputs) | **11.82** | 17.20 | 0.877 | **77.5%** | 53.8% |
| **AirAware** (linear regression on the change) | 12.00 | **17.11** | **0.878** | 77.3% | 42.3% |
| *Upper bound: realized weather + CAMS (not available on the day)* | *10.44* | *15.40* | *0.901* | *82.6%* | *61.5%* |

MAE is in AQI points. Poor-day recall is the share of days that were actually Poor or worse (AQI > 200) that the method
also called Poor or worse; there were only 26 such days in the test, so those percentages are noisy.

**Is the gain real?** Diebold-Mariano tests on absolute error, with each day's error averaged over the two cities so the
Newey-West variance (7 lags) runs along time: next day, AirAware against persistence gives p = 0.196 and station history
only gives p = 0.127. **Neither is significant next day.** An earlier version of this README reported p < 0.001; that
compared the upper-bound model and pooled the two cities' series, and it does not hold up.

**Further ahead.** The same walk-forward test for each horizon:

| Days ahead | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
|---|---:|---:|---:|---:|---:|---:|---:|
| AirAware MAE | 12.0 | 17.1 | 19.3 | 20.0 | 20.7 | 22.3 | 23.2 |
| Station history only MAE | 12.1 | 17.3 | 19.7 | 21.2 | 22.1 | 22.9 | 23.2 |
| Persistence MAE | 12.4 | 17.9 | 21.0 | 23.3 | 25.3 | 26.4 | 26.7 |
| AirAware vs persistence, DM p | 0.20 | 0.20 | 0.12 | **0.04** | **0.003** | **0.01** | **0.009** |
| AirAware 80% range coverage | 84% | 83% | 82% | 82% | 81% | 78% | 88% |
| *Upper bound MAE (not live)* | *10.4* | *14.3* | *16.5* | *17.8* | *18.0* | *18.7* | *18.6* |

**Uncertainty.** The 80% range is split conformal: the 10th and 90th percentiles of AirAware's own errors in earlier
walk-forward months (in-sample errors until 60 exist). The chance of a Poor day is the share of those past errors that
would lift the forecast above 200. On the test months the ranges held the real AQI 78-88% of the time.

**Explanations.** AirAware is linear, so each forecast splits exactly into today's AQI, a baseline change, and one
push per input (coefficient × standardised input). The analysis app shows the largest pushes.

### Insights (`airaware/insights.py`)

- **Daily rhythm.** Hourly PM since January 2025, averaged by month and hour. In winter the 7-10 am rush is the worst
  time of day and mid-afternoon the cleanest, as night-time inversions trap particles until the sun mixes the air.
- **Diwali.** Each day's AQI minus the average of days 30 to 11 before Diwali. The AQI rises by about 145 points at the
  peak in both cities, one to two days before Diwali (Mumbai: 2021, 2022, 2025; Pune: 2025 only). Some of the rise is the
  normal post-monsoon worsening, so this is an upper bound on the festival's own effect.
- **Which particle.** PM10 (dust) sets the AQI on most days; PM2.5 (smoke) takes over in winter, on almost every
  December day in Pune.
- **Station trust.** Over the last 90 days five Mumbai stations and two Pune stations (Katraj Dairy, Thergaon) barely move with the rest of their
  city (correlation below 0.6), more likely faulty or badly sited sensors than different air.
- **Cigarettes.** Berkeley Earth's rule of thumb, 22 µg/m³ of PM2.5 for a day ≈ one cigarette: the past year's air was
  about 670 cigarettes in Pune and 540 in Mumbai.

What this shows:

- Next day, nothing beats "tomorrow = today" by much once the inputs are fair: AirAware is 3% better and the difference is
  not statistically significant. It wins in Pune (12.1 vs 13.4) and is slightly worse in Mumbai (11.9 vs 11.5).
- The model earns its keep further ahead: 18% lower error than persistence at 5 days, significant from 4 to 7 days ahead,
  because it falls back on the season and the weather forecast while a repeated reading goes stale.
- Weather forecasts add a little on top of station history (12.00 vs 12.11 next day, 20.7 vs 22.1 at 5 days).
- The upper bound (10.4 next day) shows how much perfect weather and particle forecasts would be worth. The gap between it
  and AirAware is the price of not having archived CAMS forecasts.
- AirAware catches fewer Poor days than persistence (42% vs 62% of 26 days): a regression to the mean that smooths spikes.
  That trade-off is a fair one to discuss in the viva.
- Gradient boosting is slightly more accurate next day (11.8). AirAware stays linear so every forecast can be explained exactly.

## Limitations

- The training data is small and has a gap: no usable data for 2023–2024.
- City AQI is a station average, so it shifts a little as stations go offline and come back.
- CAMS keeps no archive of its past forecasts, so no fair test of CAMS as an input is possible; it appears only in the upper-bound experiment. The weather archive starts in June 2024 and lacks boundary-layer height.
- About a year of test data (662 next-day forecasts, 26 Poor days): small enough that the next-day differences are within noise.
- Live forecasts are given the best weather known when they run (ERA5 for past days, Open-Meteo's forecast ahead), which is slightly fresher than the archived runs the model was trained on.
- The AQI is computed from PM only, not CPCB's official multi-pollutant AQI. The two agree on most days.
- Without an OpenAQ key the archive runs about four days behind, so "tomorrow" is really a 5-day-ahead forecast from
  the last reading. The live path (OpenAQ API) is covered by tests with recorded responses but has not been run
  against the real API, for want of a key.
- Email alerts are written and tested with a stub, but need an SMTP server configured to send.
- An area's estimate interpolates between stations, so it cannot see a source between them (a busy junction,
  a construction site). Areas far from any station fall back to the nearest one.

## Project layout

```
airaware/aqi.py         CPCB breakpoints, categories, health advice, personal advice by health group
airaware/data.py        download, cleaning, daily city table, station table, weather and CAMS
airaware/model.py       features, baselines, walk-forward evaluation, ranges, significance test, live forecast
airaware/insights.py    daily rhythm, Diwali effect, dominant particle, station agreement, cigarettes
airaware/live.py        live weather, any-point estimates, place names, optional OpenAQ readings, throttling
airaware/server/        FastAPI app: db, auth, public, account, admin, core (jobs), manage (CLI)
frontend/src/           React app: pages (Home, Explore, Compare, Science, TrackRecord, About, Auth, Me, Admin)
app.py                  Streamlit analysis app
data/*.csv              cleaned daily, station and hourly tables (raw downloads cached in data/raw/)
tests/                  model, cleaning, leakage, insights; server: auth, permissions, alerts, moderation, limits
frontend/e2e/           browser tests: forecast, any area, sign-up, places, alerts, admin guard
Dockerfile, compose.yaml  self-hosting
```

## Roadmap

Live CPCB readings by default, more cities (the pipeline is city-agnostic), push and WhatsApp alerts, and low-cost
sensors from housing societies to fill the gaps between stations.
