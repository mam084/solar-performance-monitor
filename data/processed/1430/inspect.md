# Column report: 1430 NREL Mesa 1-axis

_report v2_

Years in the bucket: 2008, 2009, 2010, 2011, 2012, 2013, 2014, 2015, 2016, 2017
Sample: 2013-06-01 to 2013-06-14

## What each metric is

```
 metric_id    sensor_name         common_name units raw_units
      5041 poa_irradiance      Irradiance POA W/m^2     W/m^2
      5042   ambient_temp Temperature ambient     C         C
      5043    module_temp  Temperature module     C         C
      5044     wind_speed          Wind speed   m/s       m/s
      5045      kWh_gross     AC energy other     -       kWh
      5046        kWh_net     AC energy other     -       kWh
      5047             PR                  PR     -         -
      5074       ac_power            AC power     W         W
      5075     dc_voltage          DC voltage     V         V
      5076     dc_current          DC current     A         A
      5077       dc_power            DC power     W         W
```

## Columns in the sample

```
=== year=2013/month=6/day=3/system_1430__date_2013_06_03.snappy.000.parquet  (7 columns, 2013-06-03 00:00:00 -> 2013-06-03 23:45:00)
             non_null_%    min  median      max
metric_5041       100.0   0.51  182.83  1090.50
metric_5042       100.0  13.24   22.33    29.19
metric_5043       100.0  10.12   23.20    53.37
metric_5045       100.0   0.00   25.50   155.00
metric_5046       100.0  -1.00   25.50   155.00
metric_5047        96.9   0.00    0.76     0.88
metric_5074       100.0   0.00   54.07   315.76

--- suggested mapping for config/sites.yaml (check before using) ---
    columns:
      ac_power: null
      poa_irradiance: null
      module_temp: null
      ambient_temp: null
      wind_speed: null
```
