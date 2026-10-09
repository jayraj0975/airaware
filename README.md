# AirAware

A website that forecasts the Air Quality Index (AQI) for **Pune** and **Mumbai** up to a week ahead, from real
government monitoring stations, live weather and the Copernicus CAMS particle forecast. Click any area on the map to
see its estimated air quality, its forecast, the weather there right now and the nearest stations. Every forecast comes
with an 80% range, the chance of a Poor day and health advice.

DS/ML mini project. Fits the suggested title *Weather Data Analysis and Prediction System*.

## Run it

The website, on your own machine:

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn airaware.web:app --port 8000   # http://localhost:8000
```

Or with Docker, which keeps itself up to date and restarts on boot:

```sh
docker build -t airaware . && docker run -d --name airaware --restart unless-stopped -p 8000:8000 -v airaware-data:/app/data airaware
# or: docker compose up -d   (needs the compose plugin)
```

**Live station readings.** The public archive runs about four days behind. A free OpenAQ API key
([explore.openaq.org](https://explore.openaq.org), two minutes to get) switches the site to live hourly CPCB readings, so
"tomorrow" becomes a true next-day forecast: start it with `OPENAQ_API_KEY=... uvicorn ...` or `docker run -e OPENAQ_API_KEY=...`.

Other commands:

```sh
.venv/bin/streamlit run app.py          # the analysis app with replay, what-if sliders and per-forecast explanations
.venv/bin/python -m airaware.model      # re-run the evaluation, writes reports/metrics.md
.venv/bin/python -m airaware.data       # refresh data/daily.csv and data/stations.csv (first run ~10 min, then ~2 min)
.venv/bin/python -m pytest              # tests
```

## The website

| Section | What it shows |
|---|---|
| Header | City switch, and whether station readings are live or from the archive. |
| Today | AirAware's forecast for today with its range, chance of a Poor day and health advice; tomorrow; the cleanest day and hours ahead; the weather now. |
| Pick any area | A map of every station coloured by its AQI. Click anywhere: the area's name, estimated AQI (inverse-distance weighting of stations within 12 km), its forecast for the coming days, the weather there now, and the nearest stations. |
| Forecast and weather | The last six weeks and the week ahead with the 80% range; temperature, humidity and mixing height for the next 48 hours. |
| Stations | Every station's latest reading and whether it agrees with the rest of the city. |
| Insights | When in the day the air is cleanest, the Diwali effect, the year in air, the past year in cigarettes. |
| How good is it? | AirAware against baselines with the significance test, error 1-7 days ahead, what the model relies on. |

The site refreshes itself: archive readings, weather and CAMS every 6 hours (then the models retrain), and live readings
every hour when a key is set. The API is plain JSON: `/api/status`, `/api/overview?city=`, `/api/stations?city=`,
`/api/area?lat=&lon=`, `/api/model`, `/api/insights?city=`.

## The analysis app (Streamlit)

| Tab | What it shows |
|---|---|
| Right now | The latest measured day, then AirAware's forecast for today and tomorrow with an 80% range, the chance of a Poor-or-worse day and health advice. **Plan your week**: the cleanest day coming up, the usually cleanest hours that month, and the last measured day in cigarettes. A chart joins the last six weeks of readings to the week-ahead forecast. **Fetch latest data** in the sidebar downloads new readings and a fresh weather forecast. |
| Replay a day | Pick any evening from October 2025 on: what AirAware said, its range, and what actually happened. Sliders change tomorrow's temperature, humidity, rain and wind. **Why this forecast?** splits the forecast exactly into the push from each input. |
| Stations | Map of every CPCB station in the city coloured by its latest AQI, a table of their PM2.5 and PM10, and **Which stations can you trust?**: each station's correlation with and bias against the rest of the city over 90 days. |
| Insights | Hour-by-month heatmap of when the air is cleanest, the Diwali effect, which particle sets the AQI each month, and a year of air in cigarettes. |
| Explore the data | Daily AQI, the monthly pattern (clean monsoon, bad winter), share of days per AQI category, weather against AQI, data coverage per year. |
| How good is it? | AirAware against baselines, a significance test, error 1-7 days ahead, range coverage, error by month, a category confusion table, which inputs matter, and a CSV of every test forecast. |

## Data

- **Air quality**: CPCB continuous monitoring stations (14 in Pune including Pimpri-Chinchwad, 23 in Mumbai; Navi Mumbai and Vasai excluded),
  15-minute readings from [OpenAQ's public archive](https://openaq.org) (`openaq-data-archive` on AWS, no account needed).
- **Weather**: ERA5 reanalysis from [Open-Meteo](https://open-meteo.com) (no key): temperature, humidity, rain, wind,
  pressure and boundary-layer (mixing) height at each city centre. Open-Meteo's forecast fills the last few days ERA5
  has not reached yet and the week ahead. Current conditions come from Open-Meteo's live forecast API.
- **CAMS**: the Copernicus Atmosphere Monitoring Service PM2.5 and PM10, through Open-Meteo (no key): its analysis for
  every day since August 2022 and its forecast for the next four days. CAMS reads 2-4× low in Indian cities because
  it misses local road dust, but it rises and falls with the stations (correlation 0.88 in Pune), so it is a strong
  input. On its own, even scaled to the stations, it was a worse live estimate than the four-day-old reading (Pune MAE
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

Each row is one city on one evening D. The features are what is known that evening:

- today's AQI, PM2.5 and PM10, yesterday's and the day before's AQI, and the 7-day average;
- today's weather and **the target day's weather**; at forecast time that comes from a weather forecast;
- today's CAMS particles and **CAMS's forecast for the target day**;
- the season, the day of the week, whether it is Diwali week, and the city.

The target is the AQI on D+h for h = 1 to 7 days; the weather and CAMS inputs are those of the target day. A test (`tests/test_airaware.py`) checks that no feature uses anything from the target day.

AQI changes slowly from day to day, so a model that predicts the AQI level directly lost to simply saying
"tomorrow = today". AirAware instead predicts the **change** from today, using ridge (linear) regression.

**Walk-forward evaluation.** At the start of each month from October 2025, every method is retrained on every row whose
target had already been measured, and then forecasts that month. This covers 660 next-day city forecasts up to
5 October 2026, including winter 2025–26.

| Method | MAE | RMSE | R² | Category accuracy | Poor-day recall |
|---|---:|---:|---:|---:|---:|
| Persistence (tomorrow = today) | 12.42 | 18.10 | 0.864 | 76.8% | 61.5% |
| 7-day average | 17.95 | 25.51 | 0.730 | 66.5% | 11.5% |
| Seasonal average (city, month) | 28.87 | 40.07 | 0.333 | 56.4% | 0% |
| Linear regression on the AQI level | 12.69 | 18.16 | 0.863 | 79.1% | **65.4%** |
| Gradient boosting on the change | 11.28 | 16.54 | 0.886 | 79.8% | 50.0% |
| AirAware without tomorrow's forecasts (weather and CAMS) | 12.24 | 17.56 | 0.872 | 77.4% | 57.7% |
| AirAware without CAMS | 11.56 | 16.63 | 0.885 | 79.5% | 61.5% |
| **AirAware** (linear regression on the change) | **10.44** | **15.41** | **0.901** | **82.6%** | 61.5% |

MAE is in AQI points. Poor-day recall is the share of days that were actually Poor or worse (AQI > 200) that the
method also called Poor or worse.

**Is the gain real?** A Diebold-Mariano test (absolute error, Newey-West variance over 7 days because daily errors are
autocorrelated) gives statistic −5.37, p < 0.001: AirAware's lower error is statistically significant.

**Further ahead.** The same walk-forward test for each horizon, against repeating the last reading:

| Days ahead | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
|---|---:|---:|---:|---:|---:|---:|---:|
| AirAware MAE | 10.4 | 14.3 | 16.5 | 17.8 | 18.1 | 18.7 | 18.6 |
| Last reading repeated MAE | 12.4 | 17.9 | 21.0 | 23.3 | 25.3 | 26.4 | 26.7 |
| AirAware 80% range coverage | 88% | 88% | 87% | 85% | 86% | 86% | 85% |

**Uncertainty.** The 80% range is split conformal: the 10th and 90th percentiles of AirAware's own errors in earlier
walk-forward months (in-sample errors until 60 exist). The chance of a Poor day is the share of those past errors that
would lift the forecast above 200. On the test months the ranges held the real AQI 85-88% of the time, slightly more
than the 80% promised.

**Explanations.** AirAware is linear, so each forecast splits exactly into today's AQI, a baseline change, and one
push per input (coefficient × standardised input). The app shows the largest pushes.

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

- AirAware beats "tomorrow = today" by 16% on MAE and gets the AQI category right on 83% of days instead of 77%.
  The advantage grows with the horizon: 21% at 3 days, 29% at 5.
- It wins in both cities: Pune MAE 10.6 vs 13.4, Mumbai 10.2 vs 11.5.
- CAMS is the biggest single gain: without it, MAE rises from 10.44 to 11.56. Without any target-day forecasts
  (weather and CAMS), it rises to 12.24.
- Temperature is the strongest weather input. Holding today fixed, the model expects worse air when tomorrow is warmer than today. This is an association learned from about 20 months of data, not a proven cause.
- For catching Poor days, plain linear regression on the level does best (65%). That trade-off is a fair one to discuss in the viva.

## Limitations

- The training data is small and has a gap: no usable data for 2023–2024.
- City AQI is a station average, so it shifts a little as stations go offline and come back.
- The test uses actual (ERA5) weather and the CAMS analysis in place of their forecasts, so real-time accuracy will be
  a little worse, more so several days ahead where those forecasts are less accurate.
- Live forecasts mix two weather sources: ERA5 for the past, Open-Meteo's forecast model for the last few days and the week ahead.
- The AQI is computed from PM only, not CPCB's official multi-pollutant AQI. The two agree on most days.
- Without an OpenAQ key the archive runs about four days behind, so "tomorrow" is really a 5-day-ahead forecast from
  the last reading. The live path (OpenAQ API) is covered by tests with recorded responses but has not been run
  against the real API without a key.
- An area's estimate interpolates between stations, so it cannot see a source between them (a busy junction,
  a construction site). Areas far from any station fall back to the nearest one.

## Project layout

```
airaware/aqi.py      CPCB breakpoints, sub-index, categories, health advice
airaware/data.py     download, cleaning, daily city table, station table, weather history + forecast
airaware/model.py    features, baselines, walk-forward evaluation, ranges, significance test, explanations, live forecast
airaware/insights.py daily rhythm, Diwali effect, dominant particle, station agreement, cigarette equivalent
airaware/live.py     live weather, any-point estimates, place names, optional live OpenAQ readings
airaware/web.py      FastAPI website: JSON API, background refresh, serves web/
web/                 the dashboard (HTML, CSS, JavaScript with Leaflet and Chart.js)
app.py               Streamlit analysis app
Dockerfile, compose.yaml  self-hosting
data/daily.csv       the cleaned daily city table, including the week-ahead weather (raw downloads are cached in data/raw/)
data/stations.csv    daily AQI per station with its position
data/hourly_profile.csv  average PM by city, month and hour of day
reports/metrics.md   latest evaluation
tests/               API smoke test, live-reading handling, AQI maths, cleaning rules, no-leakage checks, training cutoff, explanations, ranges, DM test, insights
```
