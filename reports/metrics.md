# AirAware results

Walk-forward test: at the start of each month from October 2025, every method is retrained on everything before that month and forecasts it. 660 city-day forecasts, up to 05 Oct 2026. Lower MAE/RMSE is better.

## Both cities

| Method                                    |    MAE |   RMSE |    R2 |   Category accuracy |   Poor-day recall |
|:------------------------------------------|-------:|-------:|------:|--------------------:|------------------:|
| Persistence (tomorrow = today)            | 12.422 | 18.097 | 0.864 |               0.768 |             0.615 |
| 7-day average                             | 17.949 | 25.511 | 0.73  |               0.665 |             0.115 |
| Seasonal average (city, month)            | 28.865 | 40.07  | 0.333 |               0.564 |             0     |
| Linear regression on the AQI level        | 12.692 | 18.16  | 0.863 |               0.791 |             0.654 |
| Gradient boosting on the change           | 11.275 | 16.539 | 0.886 |               0.798 |             0.5   |
| AirAware without tomorrow's forecasts     | 12.245 | 17.556 | 0.872 |               0.774 |             0.577 |
| AirAware without CAMS                     | 11.558 | 16.631 | 0.885 |               0.795 |             0.615 |
| AirAware: linear regression on the change | 10.437 | 15.411 | 0.901 |               0.826 |             0.615 |

## MAE by city

| Method                                    |   Pune |   Mumbai |
|:------------------------------------------|-------:|---------:|
| 7-day average                             |   19.4 |     16.5 |
| AirAware without CAMS                     |   11.6 |     11.5 |
| AirAware without tomorrow's forecasts     |   12.6 |     11.9 |
| AirAware: linear regression on the change |   10.6 |     10.2 |
| Gradient boosting on the change           |   11.8 |     10.8 |
| Linear regression on the AQI level        |   11.7 |     13.7 |
| Persistence (tomorrow = today)            |   13.4 |     11.5 |
| Seasonal average (city, month)            |   25.7 |     32   |

Diebold-Mariano test, AirAware against persistence (absolute error, Newey-West 7 lags): statistic -5.37, p = 0.000.

## Further ahead

|   Days ahead |   ('MAE', 'AirAware: linear regression on the change') |   ('MAE', 'Persistence (tomorrow = today)') |   ('80% range coverage', 'AirAware: linear regression on the change') |
|-------------:|-------------------------------------------------------:|--------------------------------------------:|----------------------------------------------------------------------:|
|            1 |                                                 10.437 |                                      12.422 |                                                                 0.883 |
|            2 |                                                 14.341 |                                      17.884 |                                                                 0.88  |
|            3 |                                                 16.511 |                                      21.021 |                                                                 0.87  |
|            4 |                                                 17.802 |                                      23.278 |                                                                 0.853 |
|            5 |                                                 18.059 |                                      25.347 |                                                                 0.86  |
|            6 |                                                 18.676 |                                      26.441 |                                                                 0.857 |
|            7 |                                                 18.648 |                                      26.748 |                                                                 0.854 |

## What the model relies on (permutation importance, MAE increase)

|                |   MAE increase |
|:---------------|---------------:|
| aqi            |          14.71 |
| temp           |           4.37 |
| cams_pm10_next |           2.04 |
| humidity_next  |           1.71 |
| temp_next      |           1.54 |
| cams_pm25_next |           1.11 |
| humidity       |           0.89 |
| cams_pm25      |           0.78 |
| blh            |           0.52 |
| cams_pm10      |           0.46 |
| aqi_7d         |           0.43 |
| wind_u_next    |           0.41 |
