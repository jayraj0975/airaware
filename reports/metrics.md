# AirAware results

Walk-forward test: at the start of each month from October 2025, every method is retrained on everything before that month and forecasts it. 654 city-day forecasts, up to 01 Oct 2026. Lower MAE/RMSE is better.

## Both cities

| Method                                    |    MAE |   RMSE |    R2 |   Category accuracy |   Poor-day recall |
|:------------------------------------------|-------:|-------:|------:|--------------------:|------------------:|
| Persistence (tomorrow = today)            | 12.951 | 19.148 | 0.858 |               0.743 |             0.581 |
| 7-day average                             | 18.565 | 25.876 | 0.741 |               0.677 |             0.323 |
| Seasonal average (city, month)            | 30.025 | 41.135 | 0.346 |               0.528 |             0     |
| Linear regression on the AQI level        | 14.133 | 20.248 | 0.842 |               0.772 |             0.742 |
| Gradient boosting on the change           | 12.338 | 18.394 | 0.869 |               0.774 |             0.484 |
| AirAware without tomorrow's weather       | 12.738 | 18.573 | 0.867 |               0.769 |             0.613 |
| AirAware: linear regression on the change | 12.057 | 17.692 | 0.879 |               0.797 |             0.645 |

## MAE by city

| Method                                    |   Pune |   Mumbai |
|:------------------------------------------|-------:|---------:|
| 7-day average                             |   20.7 |     16.5 |
| AirAware without tomorrow's weather       |   13.5 |     11.9 |
| AirAware: linear regression on the change |   12.6 |     11.5 |
| Gradient boosting on the change           |   13.3 |     11.4 |
| Linear regression on the AQI level        |   13.2 |     15   |
| Persistence (tomorrow = today)            |   14.5 |     11.5 |
| Seasonal average (city, month)            |   27.9 |     32.1 |

## What the model relies on (permutation importance, MAE increase)

|               |   MAE increase |
|:--------------|---------------:|
| aqi           |          16.07 |
| temp          |           6.06 |
| temp_next     |           3.23 |
| humidity_next |           1.39 |
| blh           |           0.67 |
| humidity      |           0.54 |
| blh_next      |           0.45 |
| aqi_7d        |           0.4  |
| pm10          |           0.34 |
| wind_u_next   |           0.32 |
| aqi_lag1      |           0.21 |
| pm25          |           0.18 |
