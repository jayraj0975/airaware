# AirAware

Forecasts the Air Quality Index (AQI) for **Pune** and **Mumbai** up to a week ahead, from real government
monitoring stations and the weather forecast. Every forecast comes with an 80% range, the chance of a Poor day,
health advice, and an exact breakdown of why the model said what it said.

DS/ML mini project. Fits the suggested title *Weather Data Analysis and Prediction System*.

## Run it

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/streamlit run app.py          # GUI at http://localhost:8501 (uses data/daily.csv, works offline)
.venv/bin/python -m airaware.model      # re-run the evaluation, writes reports/metrics.md
.venv/bin/python -m airaware.data       # refresh data/daily.csv and data/stations.csv (first run ~10 min, then ~2 min)
.venv/bin/python -m pytest              # tests
```

## The GUI

| Tab | What it shows |
|---|---|
| Right now | The latest measured day, then AirAware's forecast for today and tomorrow with an 80% range, the chance of a Poor-or-worse day and health advice. **Plan your week**: the cleanest day coming up, the usually cleanest hours that month, and the last measured day in cigarettes. A chart joins the last six weeks of readings to the week-ahead forecast. **Fetch latest data** in the sidebar downloads new readings and a fresh weather forecast. |
| Replay a day | Pick any evening from October 2025 on: what AirAware said, its range, and what actually happened. Sliders change tomorrow's temperature, humidity, rain and wind. **Why this forecast?** splits the forecast exactly into the push from each input. |
| Stations | Map of every CPCB station in the city coloured by its latest AQI, a table of their PM2.5 and PM10, and **Which stations can you trust?**: each station's correlation with and bias against the rest of the city over 90 days. |
| Insights | Hour-by-month heatmap of when the air is cleanest, the Diwali effect, which particle sets the AQI each month, and a year of air in cigarettes. |
| Explore the data | Daily AQI, the monthly pattern (clean monsoon, bad winter), share of days per AQI category, weather against AQI, data coverage per year. |
| How good is it? | AirAware against baselines, a significance test, error 1-7 days ahead, range coverage, error by month, a category confusion table, which inputs matter, and a CSV of every test forecast. |

## Data

- **Air quality**: CPCB continuous monitoring stations (8 in Pune, 23 in Mumbai; Navi Mumbai and Vasai excluded),
  15-minute readings from [OpenAQ's public archive](https://openaq.org) (`openaq-data-archive` on AWS, no account needed).
- **Weather**: ERA5 reanalysis from [Open-Meteo](https://open-meteo.com) (no key): temperature, humidity, rain, wind,
  pressure and boundary-layer (mixing) height at each city centre. Open-Meteo's forecast fills the last few days ERA5
  has not reached yet and the week ahead.

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
February 2025 to October 2026. That gives about 1,445 city-days with an AQI.

## Method

Each row is one city on one evening D. The features are what is known that evening:

- today's AQI, PM2.5 and PM10, yesterday's and the day before's AQI, and the 7-day average;
- today's weather and **tomorrow's weather**; at forecast time tomorrow's comes from a weather forecast;
- the season, the day of the week, whether it is Diwali week, and the city.

The target is the AQI on D+h for h = 1 to 7 days; the weather inputs are those of the target day. A test (`tests/test_airaware.py`) checks that no feature uses anything from the target day.

AQI changes slowly from day to day, so a model that predicts the AQI level directly lost to simply saying
"tomorrow = today". AirAware instead predicts the **change** from today, using ridge (linear) regression.

**Walk-forward evaluation.** At the start of each month from October 2025, every method is retrained on every row whose
target had already been measured, and then forecasts that month. This covers 658 next-day city forecasts up to
5 October 2026, including winter 2025–26.

| Method | MAE | RMSE | R² | Category accuracy | Poor-day recall |
|---|---:|---:|---:|---:|---:|
| Persistence (tomorrow = today) | 12.95 | 19.12 | 0.858 | 74.5% | 58.1% |
| 7-day average | 18.52 | 25.83 | 0.741 | 67.9% | 32.3% |
| Seasonal average (city, month) | 29.92 | 41.03 | 0.346 | 52.7% | 0% |
| Linear regression on the AQI level | 14.12 | 20.21 | 0.841 | 77.4% | **74.2%** |
| Gradient boosting on the change | 12.33 | 18.37 | 0.869 | 77.4% | 48.4% |
| AirAware without tomorrow's weather | 12.74 | 18.55 | 0.866 | 76.9% | 61.3% |
| **AirAware** (linear regression on the change) | **12.06** | **17.67** | **0.879** | **79.8%** | 64.5% |

MAE is in AQI points. Poor-day recall is the share of days that were actually Poor or worse (AQI > 200) that the
method also called Poor or worse.

**Is the gain real?** A Diebold-Mariano test (absolute error, Newey-West variance over 7 days because daily errors are
autocorrelated) gives statistic −2.62, p = 0.009: AirAware's lower error is statistically significant.

**Further ahead.** The same walk-forward test for each horizon, against repeating the last reading:

| Days ahead | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
|---|---:|---:|---:|---:|---:|---:|---:|
| AirAware MAE | 12.1 | 16.5 | 18.9 | 20.5 | 21.0 | 21.8 | 22.3 |
| Last reading repeated MAE | 13.0 | 18.3 | 21.5 | 24.0 | 25.8 | 26.7 | 26.7 |
| AirAware 80% range coverage | 88% | 88% | 85% | 86% | 86% | 87% | 86% |

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
- **Station trust.** Over the last 90 days five Mumbai stations and one Pune station barely move with the rest of their
  city (correlation below 0.6), more likely faulty or badly sited sensors than different air.
- **Cigarettes.** Berkeley Earth's rule of thumb, 22 µg/m³ of PM2.5 for a day ≈ one cigarette: the past year's air was
  about 670 cigarettes in Pune and 540 in Mumbai.

What this shows:

- AirAware beats "tomorrow = today" by about 7% on MAE and gets the AQI category right on 80% of days instead of 74%.
  The advantage grows with the horizon: 13% at 3 days, 19% at 5.
- Most of the next-day gain is in Pune: MAE 12.6 vs 14.4. In Mumbai it roughly ties persistence (11.6 vs 11.5).
- Tomorrow's weather helps: without it, MAE rises from 12.06 to 12.74.
- Temperature is the strongest weather input. Holding today fixed, the model expects worse air when tomorrow is warmer than today. This is an association learned from about 20 months of data, not a proven cause.
- For catching Poor days, plain linear regression on the level does best (74%). That trade-off is a fair one to discuss in the viva.

## Limitations

- The training data is small and has a gap: no usable data for 2023–2024.
- City AQI is a station average, so it shifts a little as stations go offline and come back.
- The test uses actual (ERA5) weather in place of a weather forecast, so real-time accuracy will be a little worse,
  more so several days ahead where weather forecasts themselves are less accurate.
- Live forecasts mix two weather sources: ERA5 for the past, Open-Meteo's forecast model for the last few days and the week ahead.
- The AQI is computed from PM only, not CPCB's official multi-pollutant AQI. The two agree on most days.
- The OpenAQ archive runs about four days behind, so "tomorrow" is really a 5-day-ahead forecast from the last reading.
  A live CPCB feed (data.gov.in, needs an API key) would cut that to a true next-day forecast.

## Project layout

```
airaware/aqi.py      CPCB breakpoints, sub-index, categories, health advice
airaware/data.py     download, cleaning, daily city table, station table, weather history + forecast
airaware/model.py    features, baselines, walk-forward evaluation, ranges, significance test, explanations, live forecast
airaware/insights.py daily rhythm, Diwali effect, dominant particle, station agreement, cigarette equivalent
app.py               Streamlit GUI
data/daily.csv       the cleaned daily city table, including the week-ahead weather (raw downloads are cached in data/raw/)
data/stations.csv    daily AQI per station with its position
data/hourly_profile.csv  average PM by city, month and hour of day
reports/metrics.md   latest evaluation
tests/               AQI maths, cleaning rules, no-leakage checks, training cutoff, explanations, ranges, DM test, insights
```
