# Column report: 4902 NIST Ground Array

_report v2_

Years in the bucket: 2014, 2015, 2016, 2017, 2018
Sample: 2016-06-01 to 2016-06-14

## What each metric is

```
 metric_id           sensor_name           common_name units raw_units
     82591      CR1000Temp_C_Avg Temperature enclosure     C         C
     82592          DoorOpen_Min          System other     -         -
     82593          Pyra1_mV_Avg        Irradiance GHI    mV        mV
     82594          Pyra2_mV_Avg        Irradiance POA    mV        mV
     82595      RefCell1_Wm2_Avg        Irradiance POA W/m^2     W/m^2
     82596         AmbTemp_C_Avg   Temperature ambient     C         C
     82597    InvVDVoltage_V_Avg          System other     V         V
     82598             InvVa_Avg      AC voltage other     V         V
     82599             InvVb_Avg      AC voltage other     V         V
     82600             InvVc_Avg      AC voltage other     V         V
     82601             InvIa_Avg      AC current other     A         A
     82602             InvIb_Avg      AC current other     A         A
     82603             InvIc_Avg      AC current other     A         A
     82604          InvVDCin_Avg      DC voltage other     V         V
     82605          InvIDCin_Avg          System other     A         A
     82606           InvFreq_Avg          System other    Hz        Hz
     82607         InvPAC_kW_Avg              AC power    kW        kW
     82608       InvEtot_kWh_Max             AC energy   kWh       kWh
     82609          InvVPVin_Avg      DC voltage other     V         V
     82610         InvPDC_kW_Avg              DC power    kW        kW
     82611       InvOpStatus_Avg          System other     -         -
     82612      InvMainFault_Max          System other     -         -
     82613     InvDriveFault_Max          System other     -         -
     82614   InvVoltageFault_Max          System other     -         -
     82615      InvGridFault_Max          System other     -         -
     82616      InvTempFault_Max  Temperature inverter     -         -
     82617    InvSystemFault_Max          System other     -         -
     82618     InvSystemWarn_Max          System other     -         -
     82619      InvPVMStatus_Max          System other     -         -
     82620 SEWSAmbientTemp_C_Avg   Temperature ambient     C         C
     82621  SEWSModuleTemp_C_Avg    Temperature module     C         C
     82622  SEWSPOAIrrad_Wm2_Avg        Irradiance POA W/m^2     W/m^2
     82623          PwrMtrIa_Avg          System other     A         A
     82624          PwrMtrIb_Avg          System other     A         A
     82625          PwrMtrIc_Avg          System other     A         A
     82626        PwrMtrFreq_Avg              AC other    Hz        Hz
     82627     PwrMtrFreqMin_Min              AC other    Hz        Hz
     82628     PwrMtrFreqMax_Max              AC other    Hz        Hz
     82629    PwrMtrPhaseRev_Avg        AC power other     -         -
     82630          PwrMtrVa_Avg      AC voltage other     V         V
     82631          PwrMtrVb_Avg      AC voltage other     V         V
     82632          PwrMtrVc_Avg      AC voltage other     V         V
     82633        PwrMtrP_kW_Avg              AC power    kW        kW
     82634      PwrMtrP_kVAR_Avg        AC power other  kVAR      kVAR
     82635       PwrMtrP_kVA_Avg        AC power other   kVA       kVA
     82636    PwrMtrEdel_kWh_Max              AC power   kWh       kWh
     82637    PwrMtrErec_kWh_Max              AC power   kWh       kWh
     82638  PwrMtrEdel_kVARh_Max              AC power kVARh     kVARh
     82639  PwrMtrErec_kVARh_Max              AC power kVARh     kVARh
     82640          PwrMtrPF_Avg        AC power other     -         -
     82641    PwrMtrVaTHDMax_Max      AC voltage other     %         %
     82642    PwrMtrVbTHDMax_Max      AC voltage other     %         %
     82643    PwrMtrVcTHDMax_Max      AC voltage other     %         %
     82644  ShuntCurrent_A_Avg_1      DC current other     A         A
     82645  ShuntCurrent_A_Avg_2      DC current other     A         A
     82646  ShuntCurrent_A_Avg_3      DC current other     A         A
     82647  ShuntCurrent_A_Avg_4      DC current other     A         A
     82648  ShuntCurrent_A_Avg_5      DC current other     A         A
     82649  ShuntCurrent_A_Avg_6      DC current other     A         A
     82650  ShuntCurrent_A_Avg_7      DC current other     A         A
     82651     ShuntPDC_kW_Avg_1        DC power other    kW        kW
     82652     ShuntPDC_kW_Avg_2        DC power other    kW        kW
     82653     ShuntPDC_kW_Avg_3        DC power other    kW        kW
     82654     ShuntPDC_kW_Avg_4        DC power other    kW        kW
     82655     ShuntPDC_kW_Avg_5        DC power other    kW        kW
     82656     ShuntPDC_kW_Avg_6        DC power other    kW        kW
     82657     ShuntPDC_kW_Avg_7        DC power other    kW        kW
     82658   ShuntEtot_kWh_Max_1       DC energy other   kWh       kWh
     82659   ShuntEtot_kWh_Max_2       DC energy other   kWh       kWh
     82660   ShuntEtot_kWh_Max_3       DC energy other   kWh       kWh
     82661   ShuntEtot_kWh_Max_4       DC energy other   kWh       kWh
     82662   ShuntEtot_kWh_Max_5       DC energy other   kWh       kWh
     82663   ShuntEtot_kWh_Max_6       DC energy other   kWh       kWh
     82664   ShuntEtot_kWh_Max_7       DC energy other   kWh       kWh
     82665       WindSpeedAve_ms              AC other   m/s       m/s
     82666        WindDirAve_deg              AC other   Deg       Deg
     82667     WindDirStdDev_deg              AC other   Deg       Deg
     82668      WindSpeed_ms_Max              AC other   m/s       m/s
     82669         WindRef_V_Min              AC other     V         V
     82670   WindHeatStateID_Avg              AC other     -         -
     82671         WindValid_Avg              AC other     -         -
     82672         Battery_V_Min    DC voltage battery     V         V
     82673         Battery_A_Avg    DC current battery     A         A
     82674            Load_A_Avg          System other     A         A
     82675          ChgState_Min         Battery other     -         -
     82676         ChgSource_Min         Battery other     -         -
     82677            CkBatt_Max         Battery other     -         -
     82678          Qloss_Ah_Max          System other    Ah        Ah
     82679           RTD_C_Avg_1 Temperature backsheet     C         C
     82680           RTD_C_Avg_2 Temperature backsheet     C         C
     82681           RTD_C_Avg_3 Temperature backsheet     C         C
     82682           RTD_C_Avg_4 Temperature backsheet     C         C
     82683           RTD_C_Avg_5 Temperature backsheet     C         C
     82684           RTD_C_Avg_6 Temperature backsheet     C         C
     82685           RTD_C_Avg_7 Temperature backsheet     C         C
     82686           RTD_C_Avg_8 Temperature backsheet     C         C
     82687           RTD_C_Avg_9 Temperature backsheet     C         C
     82688          RTD_C_Avg_10 Temperature backsheet     C         C
```

## Columns in the sample

```
=== year=2016/month=6/day=3/system_4902__date_2016_06_03.snappy.000.parquet  (98 columns, 2016-06-03 00:00:00 -> 2016-06-03 23:59:00)
              non_null_%         min      median         max
metric_82591       100.0       21.04       23.18       37.05
metric_82592       100.0        0.00        0.00        0.00
metric_82593       100.0       -0.02        0.28        9.43
metric_82594       100.0       -0.01        0.30       10.14
metric_82595       100.0        0.40       37.94     1131.00
metric_82596       100.0       20.15       22.12       30.25
metric_82597       100.0        0.55      317.50      387.00
metric_82598       100.0      266.40      274.50      279.70
metric_82599       100.0      265.60      273.60      279.00
metric_82600       100.0      263.30      270.80      275.90
metric_82601       100.0        0.00       10.77      299.40
metric_82602       100.0        0.00       11.63      299.30
metric_82603       100.0        0.00       11.54      300.00
metric_82604       100.0        1.15      316.75      386.80
metric_82605       100.0        0.00       33.52      882.00
metric_82606       100.0       60.10       60.15       60.24
metric_82607       100.0        0.00        6.22      246.60
metric_82608       100.0  1374869.00  1375197.50  1375752.00
metric_82609       100.0       21.24      318.10      388.50
metric_82610       100.0        0.00       11.60      268.50
metric_82611       100.0        0.00        5.00        5.00
metric_82612       100.0        0.00        0.00        0.00
metric_82613       100.0        0.00        0.00        0.00
metric_82614       100.0        0.00        0.00        0.00
metric_82615       100.0        0.00        0.00        0.00
metric_82616       100.0        0.00        0.00        0.00
metric_82617       100.0        0.00        0.00        0.00
metric_82618       100.0        0.00        0.00        0.00
metric_82619       100.0        0.00        0.00        0.00
metric_82620       100.0       19.74       21.79       31.96
metric_82621       100.0       18.66       22.30       54.80
metric_82622       100.0       -0.04       36.62     1137.00
metric_82623       100.0        0.00       11.60      306.60
metric_82624       100.0        0.00       13.55      301.60
metric_82625       100.0        0.00       12.10      308.50
metric_82626       100.0       59.90       60.00       60.00
metric_82627       100.0       59.90       59.90       59.90
metric_82628       100.0       74.70       74.70       74.70
metric_82629       100.0        0.00        0.00        0.00
metric_82630       100.0      265.10      273.00      278.00
metric_82631       100.0      265.20      273.00      278.00
metric_82632       100.0      265.90      273.90      279.00
metric_82633       100.0       -0.38        6.73      246.50
metric_82634       100.0       -8.83        0.00       30.82
metric_82635       100.0        0.00        9.35      248.40
metric_82636       100.0      599.00      599.00      600.00
metric_82637       100.0  1365383.00  1365700.50  1366248.00
metric_82638       100.0    41020.00    41046.00    41066.00
metric_82639       100.0   125957.00   125979.00   126025.00
metric_82640       100.0       -1.00        1.00        1.00
metric_82641       100.0        0.98        0.98        0.98
metric_82642       100.0        0.75        0.75        0.75
metric_82643       100.0        0.92        0.92        0.92
metric_82644       100.0       -0.05        3.19      123.20
metric_82645       100.0        0.00        3.29      123.80
metric_82646       100.0        0.00        3.30      123.30
metric_82647       100.0        0.00        3.35      122.30
metric_82648       100.0        0.00        3.38      122.90
metric_82649       100.0       -0.05        3.20      122.30
metric_82650       100.0        0.00        2.88      106.00
metric_82651       100.0       -0.01        1.10       37.79
metric_82652       100.0        0.00        1.14       37.97
metric_82653       100.0        0.00        1.14       37.82
metric_82654       100.0        0.00        1.16       37.53
metric_82655       100.0        0.00        1.17       37.71
metric_82656       100.0       -0.02        1.10       37.52
metric_82657       100.0        0.00        1.00       32.52
metric_82658       100.0    42174.00    42214.50    42291.00
metric_82659       100.0    42814.00    42855.00    42932.00
metric_82660       100.0    42400.00    42440.50    42517.00
metric_82661       100.0    42248.00    42289.00    42366.00
metric_82662       100.0    43113.00    43154.50    43232.00
metric_82663       100.0    40905.00    40945.00    41021.00
metric_82664       100.0    37090.00    37122.50    37190.00
metric_82665        94.8        0.00        0.80        4.33
metric_82666       100.0        0.00      138.75      354.20
metric_82667       100.0        0.00       24.76      101.30
metric_82668        94.8        0.10        1.40       22.00
metric_82669        94.6        3.52        3.53        3.53
metric_82670       100.0        2.00        2.00        2.50
metric_82671       100.0       -1.00       -1.00       -0.15
metric_82672       100.0       13.43       13.65       13.69
metric_82673       100.0       -0.06        0.02        0.11
metric_82674       100.0        0.22        0.22        0.24
metric_82675       100.0        3.00        3.00        3.00
metric_82676       100.0        2.00        2.00        2.00
metric_82677       100.0        0.00        0.00        0.00
metric_82678       100.0        0.00        0.00        0.00
metric_82679       100.0       19.08       22.76       56.24
metric_82680       100.0       18.59       22.60       51.51
metric_82681       100.0       18.61       22.49       53.41
metric_82682       100.0       18.76       22.49       52.82
metric_82683       100.0       18.82       22.29       51.37
metric_82684       100.0       20.06       23.83       52.86
metric_82685       100.0       18.56       22.55       52.40
metric_82686       100.0       18.88       22.68       54.59
metric_82687       100.0       18.76       22.58       53.75
metric_82688       100.0       26.27       32.66       48.74

--- suggested mapping for config/sites.yaml (check before using) ---
    columns:
      ac_power: null
      poa_irradiance: null
      module_temp: null
      ambient_temp: null
      wind_speed: null
```
