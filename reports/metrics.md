# AirAware results

Walk-forward test: at the start of each month from October 2025, every method is retrained on everything before that month and forecasts it. 660 city-day forecasts, up to 05 Oct 2026. Lower MAE/RMSE is better.

## Both cities

| Method                                    |    MAE |   RMSE |    R2 |   Category accuracy |   Poor-day recall |
|:------------------------------------------|-------:|-------:|------:|--------------------:|------------------:|
| Persistence (tomorrow = today)            | 12.422 | 18.097 | 0.864 |               0.768 |             0.615 |
| 7-day average                             | 17.949 | 25.511 | 0.73  |               0.665 |             0.115 |
| Seasonal average (city, month)            | 28.865 | 40.07  | 0.333 |               0.564 |             0     |
| Linear regression on the AQI level        | 13.626 | 19.429 | 0.843 |               0.774 |             0.654 |
| Gradient boosting on the change           | 11.95  | 17.391 | 0.874 |               0.789 |             0.5   |
| AirAware without tomorrow's weather       | 12.301 | 17.571 | 0.872 |               0.764 |             0.577 |
| AirAware: linear regression on the change | 11.558 | 16.631 | 0.885 |               0.795 |             0.615 |

## MAE by city

| Method                                    |   Pune |   Mumbai |
|:------------------------------------------|-------:|---------:|
| 7-day average                             |   19.4 |     16.5 |
| AirAware without tomorrow's weather       |   12.7 |     11.9 |
| AirAware: linear regression on the change |   11.6 |     11.5 |
| Gradient boosting on the change           |   12.2 |     11.7 |
| Linear regression on the AQI level        |   12.4 |     14.9 |
| Persistence (tomorrow = today)            |   13.4 |     11.5 |
| Seasonal average (city, month)            |   25.7 |     32   |

Diebold-Mariano test, AirAware against persistence (absolute error, Newey-West 7 lags): statistic -2.67, p = 0.008.

## Further ahead

|   Days ahead |   ('MAE', 'AirAware: linear regression on the change') |   ('MAE', 'Persistence (tomorrow = today)') |   ('80% range coverage', 'AirAware: linear regression on the change') |
|-------------:|-------------------------------------------------------:|--------------------------------------------:|----------------------------------------------------------------------:|
|            1 |                                                 11.558 |                                      12.422 |                                                                 0.883 |
|            2 |                                                 16.302 |                                      17.884 |                                                                 0.883 |
|            3 |                                                 18.983 |                                      21.021 |                                                                 0.867 |
|            4 |                                                 20.606 |                                      23.278 |                                                                 0.862 |
|            5 |                                                 21.291 |                                      25.347 |                                                                 0.861 |
|            6 |                                                 22.258 |                                      26.441 |                                                                 0.863 |
|            7 |                                                 22.584 |                                      26.748 |                                                                 0.861 |

## What the model relies on (permutation importance, MAE increase)

|               |   MAE increase |
|:--------------|---------------:|
| aqi           |          14.17 |
| temp          |           5.77 |
| temp_next     |           3.02 |
| humidity_next |           1.49 |
| blh           |           0.72 |
| humidity      |           0.5  |
| blh_next      |           0.48 |
| aqi_7d        |           0.4  |
| aqi_lag1      |           0.35 |
| pm10          |           0.26 |
| wind_u_next   |           0.24 |
| wind          |           0.14 |
