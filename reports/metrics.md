# AirAware results

Walk-forward test: at the start of each month from October 2025, every method is retrained on everything before that month and forecasts it. 658 city-day forecasts, up to 05 Oct 2026. Lower MAE/RMSE is better.

## Both cities

| Method                                    |    MAE |   RMSE |    R2 |   Category accuracy |   Poor-day recall |
|:------------------------------------------|-------:|-------:|------:|--------------------:|------------------:|
| Persistence (tomorrow = today)            | 12.951 | 19.118 | 0.858 |               0.745 |             0.581 |
| 7-day average                             | 18.523 | 25.829 | 0.741 |               0.679 |             0.323 |
| Seasonal average (city, month)            | 29.92  | 41.025 | 0.346 |               0.527 |             0     |
| Linear regression on the AQI level        | 14.122 | 20.21  | 0.841 |               0.774 |             0.742 |
| Gradient boosting on the change           | 12.334 | 18.368 | 0.869 |               0.774 |             0.484 |
| AirAware without tomorrow's weather       | 12.74  | 18.548 | 0.866 |               0.769 |             0.613 |
| AirAware: linear regression on the change | 12.064 | 17.669 | 0.879 |               0.798 |             0.645 |

## MAE by city

| Method                                    |   Pune |   Mumbai |
|:------------------------------------------|-------:|---------:|
| 7-day average                             |   20.6 |     16.5 |
| AirAware without tomorrow's weather       |   13.5 |     12   |
| AirAware: linear regression on the change |   12.6 |     11.6 |
| Gradient boosting on the change           |   13.3 |     11.4 |
| Linear regression on the AQI level        |   13.2 |     15   |
| Persistence (tomorrow = today)            |   14.4 |     11.5 |
| Seasonal average (city, month)            |   27.8 |     32   |

Diebold-Mariano test, AirAware against persistence (absolute error, Newey-West 7 lags): statistic -2.62, p = 0.009.

## Further ahead

|   Days ahead |   ('MAE', 'AirAware: linear regression on the change') |   ('MAE', 'Persistence (tomorrow = today)') |   ('80% range coverage', 'AirAware: linear regression on the change') |
|-------------:|-------------------------------------------------------:|--------------------------------------------:|----------------------------------------------------------------------:|
|            1 |                                                 12.064 |                                      12.951 |                                                                 0.881 |
|            2 |                                                 16.548 |                                      18.325 |                                                                 0.876 |
|            3 |                                                 18.883 |                                      21.48  |                                                                 0.85  |
|            4 |                                                 20.534 |                                      23.964 |                                                                 0.862 |
|            5 |                                                 21.001 |                                      25.754 |                                                                 0.864 |
|            6 |                                                 21.836 |                                      26.686 |                                                                 0.866 |
|            7 |                                                 22.333 |                                      26.705 |                                                                 0.859 |

## What the model relies on (permutation importance, MAE increase)

|               |   MAE increase |
|:--------------|---------------:|
| aqi           |          15.96 |
| temp          |           6.04 |
| temp_next     |           3.22 |
| humidity_next |           1.39 |
| blh           |           0.67 |
| humidity      |           0.54 |
| blh_next      |           0.45 |
| aqi_7d        |           0.4  |
| pm10          |           0.33 |
| wind_u_next   |           0.32 |
| aqi_lag1      |           0.21 |
| pm25          |           0.18 |
