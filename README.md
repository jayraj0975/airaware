# AirAware

Forecasts tomorrow's Air Quality Index (AQI) for **Pune** and **Mumbai** from real government monitoring
stations and the weather, and lets you ask "what if tomorrow is cooler, rainier or windier?".

DS/ML mini project. Fits the suggested title *Weather Data Analysis and Prediction System*.

## Run it

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/streamlit run app.py          # GUI at http://localhost:8501 (uses data/daily.csv, works offline)
.venv/bin/python -m airaware.model      # re-run the evaluation, writes reports/metrics.md
.venv/bin/python -m airaware.data       # refresh data/daily.csv from the internet (first run ~10 min)
.venv/bin/python -m pytest              # tests
```

## The GUI

| Tab | What it shows |
|---|---|
| Forecast | Pick any evening from October 2025 on: today's AQI, AirAware's forecast for tomorrow, and what actually happened. Sliders change tomorrow's temperature, humidity, rain and wind to see how the forecast moves. |
| Explore the data | Daily AQI, the monthly pattern (clean monsoon, bad winter), share of days per AQI category, weather against AQI, data coverage per year. |
| How good is it? | AirAware against simple baselines, forecast against reality, and which inputs the model relies on. |

## Data

- **Air quality**: CPCB continuous monitoring stations (8 in Pune, 23 in Mumbai; Navi Mumbai and Vasai excluded),
  15-minute readings from [OpenAQ's public archive](https://openaq.org) (`openaq-data-archive` on AWS, no account needed).
- **Weather**: ERA5 reanalysis from [Open-Meteo](https://open-meteo.com) (no key): temperature, humidity, rain, wind,
  pressure and boundary-layer (mixing) height at each city centre.

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

The target is the AQI on D+1. A test (`tests/test_airaware.py`) checks that no feature uses anything from the target day.

AQI changes slowly from day to day, so a model that predicts the AQI level directly lost to simply saying
"tomorrow = today". AirAware instead predicts the **change** from today, using ridge (linear) regression.

**Walk-forward evaluation.** At the start of each month from October 2025, every method is retrained on everything
before that month and then forecasts that month. This covers 654 city-day forecasts up to 1 October 2026, including
winter 2025–26.

| Method | MAE | RMSE | R² | Category accuracy | Poor-day recall |
|---|---:|---:|---:|---:|---:|
| Persistence (tomorrow = today) | 12.95 | 19.15 | 0.858 | 74.3% | 58.1% |
| 7-day average | 18.57 | 25.88 | 0.741 | 67.7% | 32.3% |
| Seasonal average (city, month) | 30.03 | 41.14 | 0.346 | 52.8% | 0% |
| Linear regression on the AQI level | 14.13 | 20.25 | 0.842 | 77.2% | **74.2%** |
| Gradient boosting on the change | 12.34 | 18.39 | 0.869 | 77.4% | 48.4% |
| AirAware without tomorrow's weather | 12.74 | 18.57 | 0.867 | 76.9% | 61.3% |
| **AirAware** (linear regression on the change) | **12.06** | **17.69** | **0.879** | **79.7%** | 64.5% |

MAE is in AQI points. Poor-day recall is the share of days that were actually Poor or worse (AQI > 200) that the
method also called Poor or worse.

What this shows:

- AirAware beats "tomorrow = today" by about 7% on MAE and gets the AQI category right on 80% of days instead of 74%.
- Most of the gain is in Pune: MAE 12.6 vs 14.5. In Mumbai it only ties persistence (11.5).
- Tomorrow's weather helps: without it, MAE rises from 12.06 to 12.74.
- Temperature is the strongest weather input. Holding today fixed, the model expects worse air when tomorrow is warmer than today. This is an association learned from about 20 months of data, not a proven cause.
- For catching Poor days, plain linear regression on the level does best (74%). That trade-off is a fair one to discuss in the viva.

## Limitations

- The training data is small and has a gap: no usable data for 2023–2024.
- City AQI is a station average, so it shifts a little as stations go offline and come back.
- The test uses actual next-day weather in place of a weather forecast, so real-time accuracy will be a little worse.
- The AQI is computed from PM only, not CPCB's official multi-pollutant AQI. The two agree on most days.
- The OpenAQ archive runs a few days behind, so the GUI replays recent days rather than forecasting today live.

## Project layout

```
airaware/aqi.py      CPCB breakpoints, sub-index, categories
airaware/data.py     download, cleaning, daily city table
airaware/model.py    features, baselines, walk-forward evaluation
app.py               Streamlit GUI
data/daily.csv       the cleaned daily table (raw downloads are cached in data/raw/, not committed)
reports/metrics.md   latest evaluation
tests/               AQI maths, cleaning rules, no-leakage check
```
