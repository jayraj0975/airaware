# AirAware: viva guide

A short, honest briefing for presenting the project. Every number comes from `reports/metrics.md`
(`python -m airaware.model`) or from the tests.

## The project in two minutes

AirAware forecasts the Air Quality Index (AQI) for any street in Pune and Mumbai up to seven days ahead.

- **Data:** 15-minute PM2.5/PM10 readings from 37 government (CPCB) monitoring stations via OpenAQ's public archive,
  cleaned into one value per city per day (about 1,460 city-days), plus weather from Open-Meteo.
- **Model:** ridge regression on the *change* in AQI, one model per horizon (1-7 days), with 80% ranges from split
  conformal prediction.
- **Product:** a React + FastAPI web platform with accounts, saved places, alerts, pollution reports with admin
  moderation, privacy controls and an admin console. A separate Streamlit app is for analysis.

## Architecture

```
React (Vite, TypeScript, Leaflet, Chart.js)  ──JSON──▶  FastAPI
                                                         ├─ SQLite: accounts, sessions, places, alerts, audit, forecast log
                                                         ├─ MongoDB (optional): pollution reports + moderation
                                                         └─ ML core: data.py (download, clean) · model.py (train, evaluate, forecast)
Background thread: refresh data and retrain every 6 hours, log forecasts, score them when the real AQI arrives, send alerts.
Docker image (non-root after setup) · Docker Compose (tunnel and MongoDB profiles) · Railway deployment · CI on every PR.
```

**Why two databases?** Accounts are relational and need transactions and cascading deletes, which suits SQLite.
Reports are self-contained documents with a location, a moderation history, geographic queries and analytics,
which suits MongoDB (2dsphere index, `$jsonSchema` validator, `$facet` aggregation). See `docs/DATABASE.md`.

## How the model is evaluated (the part examiners probe)

1. **Walk-forward, not a random split.** From October 2025, at the start of each month every method is retrained on
   rows whose target was already measured, then forecasts that month. A random split would let the model learn from
   days after the ones it is tested on.
2. **No information from the future.** The trap in weather-driven forecasting: historical weather (ERA5) and the CAMS
   particle analysis are only known *after* the day, and are more accurate than the forecasts available on the day.
   - AirAware is trained and tested on weather **as it was actually forecast**, from Open-Meteo's archive of past
     runs. Each run was issued at least a day before the forecast is made.
   - CAMS keeps no such archive, so the served model does not use CAMS.
   - The original design, which used realized weather and CAMS, is kept only as an **upper bound** and labelled as such.
3. **Baselines on identical rows.** Persistence ("tomorrow = today"), a 7-day average, a seasonal average, a
   station-history-only model (no weather at all), linear regression on the level and gradient boosting all forecast
   exactly the same 662 next-day cases.
4. **Significance.** A Diebold-Mariano test with Newey-West variance (daily errors are autocorrelated), on each day's
   error averaged over the two cities.
5. **Regression tests** (`tests/test_airaware.py`) prove the rules hold:
   - every training target was measured before the forecast;
   - no feature changes when any later AQI changes;
   - issued-forecast columns come from runs issued before the forecast day;
   - the benchmark ignores weather and CAMS;
   - every method is scored on the same rows;
   - results are reproducible.

## Results to quote

| | AirAware | Station history only | Persistence | Upper bound (not live) |
|---|---:|---:|---:|---:|
| Next-day MAE (AQI points) | 12.00 | 12.11 | 12.42 | 10.44 |
| 5-day MAE | 20.7 | 22.1 | 25.3 | 18.0 |

- **Next day:** 3% better than persistence, **not statistically significant** (p = 0.20). Say this plainly: AQI is so
  persistent that tomorrow is hard to beat.
- **Further ahead:** the gain grows and **is significant from 4 to 7 days ahead** (p = 0.003 to 0.04), 18% at 5 days.
  A repeated reading goes stale, while the model falls back on the season and the weather forecast.
- **Ranges:** the 80% ranges held the real AQI 78-88% of the time across horizons.
- **By city:** better in Pune (12.1 vs 13.4), slightly worse in Mumbai next day (11.9 vs 11.5).
- **Poor days:** fewer caught than persistence (42% vs 62%), because the model smooths spikes. There were only 26 such
  days, so this is noisy.
- **Learners:** gradient boosting is slightly better next day (11.8). The linear model was kept so each forecast splits
  exactly into per-input contributions.

## Questions to expect

**"Your earlier README said 16% better with p < 0.001. Which is true?"** That figure used realized weather and CAMS
that nobody has on the day, and its significance test ran the two cities' series together as one timeline. With
inputs as they were really available, the next-day gain is 3% and not significant. The project now reports the honest
version and keeps the old one only as a labelled upper bound.

**"Why predict the change rather than the level?"** AQI moves slowly. A level model must relearn "tomorrow is like
today" from the features and loses to persistence. Predicting the change makes persistence the starting point.

**"Why ridge regression?"** About 1,460 city-days is small. A regularised linear model is stable, fast to retrain
every 6 hours and fully explainable. Gradient boosting was tested and is only marginally better.

**"How do you know the ranges are honest?"** They are built only from errors on earlier months, then checked on later
months: 78-88% coverage for a promised 80%.

**"What happens when MongoDB is down?"** Report features return a clear 503 within two seconds. Everything else keeps
working. Export and account deletion refuse rather than silently skipping reports. This is tested against an
unreachable server.

**"How is the site secured?"**
- scrypt password hashes;
- HttpOnly session cookies, with only a hash of each token stored;
- a custom header on every write, which blocks cross-site requests;
- atomic rate limits;
- admins created only from the server command line, with two-step sign-in required;
- 69 automated attacks in `security/attack.py`, passing against both databases.

**"Is it DPDP Act compliant?"** Say what is implemented, not a legal verdict: consent at sign-up, separate consent for
health information, data export, correction, deletion, privacy requests with an admin inbox, retention limits and no
tracking. A legal review was not part of this project.

## Limitations to state before being asked

- About one year of test data; next-day differences are within noise.
- No archived CAMS forecasts, so CAMS cannot be tested fairly. The weather archive starts in June 2024 and lacks
  boundary-layer height.
- Without an OpenAQ API key the public archive runs about four days behind, so "tomorrow" is really a 5-day forecast
  from the last reading.
- The AQI uses PM only, not CPCB's full multi-pollutant AQI.
- Area estimates interpolate between stations and cannot see a source between them.
- Email alerts need an SMTP server, and live OpenAQ readings need a key. Neither has been run against the real service.
- The AD syllabus document itself was not available. The MongoDB module follows the requirement as stated (GUI +
  MongoDB). Whether one project may serve both the DSML and AD mini projects is for the faculty to confirm.
