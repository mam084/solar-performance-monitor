# Column report: 1367 City of Henderson Aquatic Complex

_report v2_

Years in the bucket: 2013, 2014, 2015, 2016, 2017, 2018, 2019, 2020
Sample: 2017-06-01 to 2017-06-14

## What each metric is

```
 metric_id    sensor_name         common_name units raw_units
      3082   dc_voltage_1          DC voltage     V         V
      3083     ac_power_1            AC power     W         W
      3084 ac_frequency_1            AC other    Hz        Hz
      3085   dc_voltage_2          DC voltage     V         V
      3086     ac_power_2            AC power     W         W
      3087 ac_frequency_2            AC other    Hz        Hz
      3088   dc_voltage_3          DC voltage     V         V
      3089     ac_power_3            AC power     W         W
      3090 ac_frequency_3            AC other    Hz        Hz
      3091       ac_power            AC power     W         W
      4193 ambient_temp_K Temperature ambient     C         C
      4194  module_temp_K  Temperature module     C         C
      4195 poa_irradiance      Irradiance POA W/m^2     W/m^2
      4196 wind_speed_mph          Wind speed   m/s       m/s
```

## Columns in the sample

```
=== year=2017/month=6/day=3/system_1367__date_2017_06_03.snappy.000.parquet  (13 columns, 2017-06-03 00:00:07 -> 2017-06-03 23:59:07)
             non_null_%     min     median        max
metric_3082        63.3    2.93     350.00     430.86
metric_3083        63.3    0.00   29609.38   48515.62
metric_3085        63.2    9.77     349.22     423.44
metric_3086        63.2    0.00   51503.91   83007.81
metric_3087        63.3    0.00      60.01      60.11
metric_3088        62.9    5.47     352.34     424.61
metric_3089        62.9    0.00   45019.53   74121.09
metric_3090        62.9    0.00      60.01      60.11
metric_3091        62.7    0.00  126953.13  205214.84
metric_4193        99.7  294.60     307.35     314.90
metric_4194        99.7  291.20     307.05     333.40
metric_4195        99.7    0.00       0.00      27.40
metric_4196        99.7    0.00       0.00      15.00

--- suggested mapping for config/sites.yaml (check before using) ---
    columns:
      ac_power: null
      poa_irradiance: null
      module_temp: null
      ambient_temp: null
      wind_speed: null
```
