# Column report: 4903 NIST Roof Array

_report v2_

Years in the bucket: 2014, 2015, 2016, 2017, 2018
Sample: 2016-06-01 to 2016-06-14

## What each metric is

```
 metric_id              sensor_name           common_name units raw_units
     82689         CR1000Temp_C_Avg Temperature enclosure     C         C
     82690             DoorOpen_Min          System other     -         -
     82691             Pyra1_mV_Avg        Irradiance GHI    mV        mV
     82692             Pyra2_mV_Avg        Irradiance GHI    mV        mV
     82693             Pyra3_mV_Avg        Irradiance POA    mV        mV
     82694             Pyra4_mV_Avg        Irradiance GHI    mV        mV
     82695             Pyra5_mV_Avg        Irradiance GHI    mV        mV
     82696             Pyra6_mV_Avg        Irradiance GHI    mV        mV
     82697             Pyra7_mV_Avg        Irradiance GHI    mV        mV
     82698             Pyra8_mV_Avg        Irradiance GHI    mV        mV
     82699         RefCell1_Wm2_Avg        Irradiance POA W/m^2     W/m^2
     82700         RefCell2_Wm2_Avg        Irradiance GHI W/m^2     W/m^2
     82701         RefCell3_Wm2_Avg        Irradiance GHI W/m^2     W/m^2
     82702            AmbTemp_C_Avg   Temperature ambient     C         C
     82703       InvVDVoltage_V_Avg          System other     V         V
     82704       GeneralFaults1_Max          System other     -         -
     82705       GeneralFaults2_Max          System other     -         -
     82706           DPCBFaults_Max          System other     -         -
     82707       HardwareFaults_Max          System other     -         -
     82708       InverterFaults_Max          System other     -         -
     82709    TemperatureFaults_Max     Temperature other     -         -
     82710             Warnings_Max          System other     -         -
     82711      NumActiveFaults_Max          System other     -         -
     82712             InvVPVIn_Avg          System other     V         V
     82713             InvVDCin_Avg      DC voltage other     V         V
     82714             InvIDCin_Avg          System other     A         A
     82715              InvIGnd_Avg          System other     A         A
     82716                InvIa_Avg      AC current other     A         A
     82717                InvIb_Avg      AC current other     A         A
     82718                InvIc_Avg      AC current other     A         A
     82719           InvIabcAvg_Avg      AC current other     A         A
     82720          InvINeutral_Avg      AC current other     A         A
     82721                InvVa_Avg      AC voltage other     V         V
     82722                InvVb_Avg      AC voltage other     V         V
     82723                InvVc_Avg      AC voltage other     V         V
     82724           InvVabcAvg_Avg      AC voltage other     V         V
     82725            InvVUnbal_Avg      AC voltage other     %         %
     82726            InvIUnbal_Avg      AC current other     %         %
     82727            InvPDC_kW_Avg              DC power    kW        kW
     82728            InvPAC_kW_Avg              AC power    kW        kW
     82729          InvVAR_kVAR_Avg        AC power other  kVAR      kVAR
     82730            InvVA_kVA_Avg        AC power other   kVA       kVA
     82731                InvPF_Avg              AC other     -         -
     82732     InvGndImped_kOhm_Avg          System other  kOhm      kOhm
     82733          InvEtot_kWh_Max             AC energy   kWh       kWh
     82734        InvEtoday_kWh_Max             AC energy   kWh       kWh
     82735    InvEyesterday_kWh_Max             AC energy   kWh       kWh
     82736              InvFreq_Avg          System other    Hz        Hz
     82737           InvOpState_Avg          System other     -         -
     82738 InvTempInternalAir_C_Avg  Temperature inverter     C         C
     82739 InvTempInverterAir_C_Avg  Temperature inverter     C         C
     82740    InvTempHeatsink_C_Avg  Temperature inverter     C         C
     82741    SEWSAmbientTemp_C_Avg   Temperature ambient     C         C
     82742     SEWSModuleTemp_C_Avg    Temperature module     C         C
     82743     SEWSPOAIrrad_Wm2_Avg          System other W/m^2     W/m^2
     82744             PwrMtrIa_Avg          System other     A         A
     82745             PwrMtrIb_Avg          System other     A         A
     82746             PwrMtrIc_Avg          System other     A         A
     82747           PwrMtrFreq_Avg              AC other    Hz        Hz
     82748        PwrMtrFreqMin_Min              AC other    Hz        Hz
     82749        PwrMtrFreqMax_Max              AC other    Hz        Hz
     82750       PwrMtrPhaseRev_Avg        AC power other     -         -
     82751             PwrMtrVa_Avg      AC voltage other     V         V
     82752             PwrMtrVb_Avg      AC voltage other     V         V
     82753             PwrMtrVc_Avg      AC voltage other     V         V
     82754           PwrMtrP_kW_Avg              AC power    kW        kW
     82755         PwrMtrP_kVAR_Avg        AC power other  kVAR      kVAR
     82756          PwrMtrP_kVA_Avg        AC power other   kVA       kVA
     82757       PwrMtrEdel_kWh_Max              AC power   kWh       kWh
     82758       PwrMtrErec_kWh_Max              AC power   kWh       kWh
     82759     PwrMtrEdel_kVARh_Max              AC power kVARh     kVARh
     82760     PwrMtrErec_kVARh_Max              AC power kVARh     kVARh
     82761             PwrMtrPF_Avg        AC power other     -         -
     82762       PwrMtrVaTHDMax_Max      AC voltage other     %         %
     82763       PwrMtrVbTHDMax_Max      AC voltage other     %         %
     82764       PwrMtrVcTHDMax_Max      AC voltage other     %         %
     82765     ShuntCurrent_A_Avg_1      DC current other     A         A
     82766     ShuntCurrent_A_Avg_2      DC current other     A         A
     82767     ShuntCurrent_A_Avg_3      DC current other     A         A
     82768     ShuntCurrent_A_Avg_4      DC current other     A         A
     82769        ShuntPDC_kW_Avg_1        DC power other    kW        kW
     82770        ShuntPDC_kW_Avg_2        DC power other    kW        kW
     82771        ShuntPDC_kW_Avg_3        DC power other    kW        kW
     82772        ShuntPDC_kW_Avg_4        DC power other    kW        kW
     82773      ShuntEtot_kWh_Max_1       DC energy other   kWh       kWh
     82774      ShuntEtot_kWh_Max_2       DC energy other   kWh       kWh
     82775      ShuntEtot_kWh_Max_3       DC energy other   kWh       kWh
     82776      ShuntEtot_kWh_Max_4       DC energy other   kWh       kWh
     82777          WindSpeedAve_ms              AC other   m/s       m/s
     82778           WindDirAve_deg              AC other   Deg       Deg
     82779        WindDirStdDev_deg              AC other   Deg       Deg
     82780         WindSpeed_ms_Max              AC other   m/s       m/s
     82781            WindRef_V_Min              AC other     V         V
     82782      WindHeatStateID_Avg              AC other     -         -
     82783            WindValid_Avg              AC other     -         -
     82784            Battery_V_Min    DC voltage battery     V         V
     82785            Battery_A_Avg    DC current battery     A         A
     82786               Load_A_Avg          System other     A         A
     82787             ChgState_Min         Battery other     -         -
     82788            ChgSource_Min         Battery other     -         -
     82789               CkBatt_Max         Battery other     -         -
     82790             Qloss_Ah_Max          System other    Ah        Ah
     82791              RTD_C_Avg_1 Temperature backsheet     C         C
     82792              RTD_C_Avg_2 Temperature backsheet     C         C
     82793              RTD_C_Avg_3 Temperature backsheet     C         C
     82794              RTD_C_Avg_4 Temperature backsheet     C         C
     82795              RTD_C_Avg_5 Temperature backsheet     C         C
     82796              RTD_C_Avg_6 Temperature backsheet     C         C
     82797              RTD_C_Avg_7 Temperature backsheet     C         C
     82798          TCTemps_C_Avg_1     Temperature other     C         C
     82799          TCTemps_C_Avg_2     Temperature other     C         C
     82800          TCTemps_C_Avg_3     Temperature other     C         C
     82801          TCTemps_C_Avg_4     Temperature other     C         C
     82802          TCTemps_C_Avg_5     Temperature other     C         C
     82803          TCTemps_C_Avg_6     Temperature other     C         C
     82804          TCTemps_C_Avg_7     Temperature other     C         C
     82805          TCTemps_C_Avg_8     Temperature other     C         C
     82806          TCTemps_C_Avg_9     Temperature other     C         C
     82807         TCTemps_C_Avg_10     Temperature other     C         C
     82808         TCTemps_C_Avg_11     Temperature other     C         C
     82809         TCTemps_C_Avg_12     Temperature other     C         C
```

## Columns in the sample

```
=== year=2016/month=6/day=3/system_4903__date_2016_06_03.snappy.000.parquet  (121 columns, 2016-06-03 00:00:00 -> 2016-06-03 23:59:00)
              non_null_%        min     median        max
metric_82689       100.0      22.31      24.16      39.94
metric_82690       100.0       0.00       0.00       0.00
metric_82691       100.0      -0.02       0.21       9.31
metric_82692       100.0      -0.02       0.23      10.09
metric_82693       100.0      -0.01       0.26      11.35
metric_82694       100.0      -0.04       0.19       8.80
metric_82695       100.0      -0.03       0.20       9.21
metric_82696       100.0      -0.01       0.23      10.45
metric_82697       100.0      -0.04       0.18       9.28
metric_82698       100.0      -0.03       0.20       9.80
metric_82699       100.0      -0.30      31.49    1179.00
metric_82700       100.0      -0.10      29.54    1161.00
metric_82701       100.0       0.41      29.36    1139.00
metric_82702       100.0      20.11      22.05      28.79
metric_82703       100.0       1.40     318.55     382.10
metric_82704       100.0       0.00       0.00       0.00
metric_82705       100.0       0.00       0.00       2.00
metric_82706       100.0       0.00       0.00       0.00
metric_82707       100.0       0.00       0.00       0.00
metric_82708       100.0       0.00       0.00       0.00
metric_82709       100.0       0.00       0.00       0.00
metric_82710       100.0       0.00       0.00       0.00
metric_82711       100.0       0.00       0.00       1.00
metric_82712       100.0       1.00     317.20     381.00
metric_82713       100.0      -2.00     316.35     382.00
metric_82714       100.0      -1.70       3.68     214.90
metric_82715       100.0      -0.50      -0.32      -0.15
metric_82716       100.0       0.00       1.00      78.50
metric_82717       100.0       0.00       2.00      79.47
metric_82718       100.0       0.00       2.00      79.88
metric_82719       100.0       0.00       1.00      78.88
metric_82720       100.0       0.00       0.00       0.00
metric_82721       100.0     264.90     272.00     277.00
metric_82722       100.0     267.90     275.00     279.50
metric_82723       100.0     267.90     275.00     280.00
metric_82724       100.0     266.90     273.90     278.50
metric_82725       100.0       0.48       0.58       0.70
metric_82726       100.0       0.00       0.00       0.00
metric_82727       100.0      -0.30       1.39      68.60
metric_82728       100.0      -0.40       1.12      65.93
metric_82729       100.0      -0.32      -0.10       0.08
metric_82730       100.0       0.05       1.42      65.88
metric_82731       100.0       0.00       0.00       1.00
metric_82732       100.0    6000.00    6000.00    6000.00
metric_82733       100.0  324213.00  324294.00  324434.00
metric_82734       100.0       0.00      84.00     228.00
metric_82735       100.0     228.00     245.00     245.00
metric_82736       100.0      59.90      59.96      60.00
metric_82737       100.0       2.00       7.00       7.00
metric_82738       100.0      32.00      37.00      46.00
metric_82739       100.0      39.00      45.00      52.00
metric_82740       100.0      31.00      47.00      60.17
metric_82741       100.0      19.92      22.03      29.08
metric_82742       100.0      18.32      22.44      65.19
metric_82743       100.0      -0.04      30.48    1185.00
metric_82744       100.0      -1.10       1.42      81.30
metric_82745       100.0      -0.14       2.17      82.60
metric_82746       100.0       0.02       2.38      82.80
metric_82747       100.0      59.90      60.00      75.67
metric_82748       100.0      17.10      59.50      59.50
metric_82749       100.0      75.60      75.60      75.60
metric_82750       100.0       1.00       1.00       1.25
metric_82751       100.0     266.80     273.90     278.10
metric_82752       100.0     267.00     273.80     278.00
metric_82753       100.0     265.90     273.00     278.00
metric_82754       100.0      -0.37       1.27      67.24
metric_82755       100.0      -2.66       0.03       0.42
metric_82756       100.0       0.08       1.29      67.30
metric_82757       100.0    1561.00    1561.00    1562.00
metric_82758       100.0  334164.00  334247.00  334391.00
metric_82759       100.0   10591.00   10594.00   10598.00
metric_82760       100.0    1554.00    1555.00    1555.00
metric_82761       100.0      -1.00      -0.92       1.00
metric_82762       100.0       0.82       0.82       0.82
metric_82763       100.0       0.79       0.79       0.79
metric_82764       100.0       0.84       0.84       0.84
metric_82765       100.0       0.00       1.39      56.86
metric_82766       100.0      -0.00       1.38      56.88
metric_82767       100.0      -0.00       1.39      56.90
metric_82768       100.0      -0.00       1.03      42.63
metric_82769       100.0       0.00       0.48      18.19
metric_82770       100.0       0.00       0.48      18.19
metric_82771       100.0       0.00       0.48      18.20
metric_82772       100.0       0.00       0.36      13.64
metric_82773       100.0       0.00      32.00     168.00
metric_82774       100.0       0.00      32.00     168.00
metric_82775       100.0       0.00      32.00     168.00
metric_82776       100.0       0.00      24.00     126.00
metric_82777       100.0       0.09       0.75       6.42
metric_82778       100.0       1.36      99.45     359.90
metric_82779       100.0       8.14      31.18      99.10
metric_82780       100.0       0.10       1.40      30.30
metric_82781        99.9       3.49       3.50       3.50
metric_82782       100.0       1.82       2.00       2.00
metric_82783       100.0      -1.00      -1.00      -1.00
metric_82784       100.0      13.13      13.55      13.62
metric_82785       100.0      -0.12       0.00       0.13
metric_82786       100.0       0.25       0.28       0.34
metric_82787       100.0       1.00       3.00       3.00
metric_82788       100.0       2.00       2.00       2.00
metric_82789       100.0       0.00       0.00       0.00
metric_82790       100.0       0.00       0.00       0.00
metric_82791       100.0      17.55      22.70      68.16
metric_82792       100.0      18.67      22.48      58.48
metric_82793       100.0      18.06      22.62      63.69
metric_82794        99.9    -242.00     -14.80     293.90
metric_82795       100.0      17.94      22.51      65.69
metric_82796       100.0      17.64      22.32      62.17
metric_82797       100.0      19.11      22.70      61.60
metric_82798       100.0      19.00      22.64      71.45
metric_82799       100.0      19.25      22.20      59.38
metric_82800       100.0      19.36      22.36      64.04
metric_82801       100.0      18.59      22.13      69.65
metric_82802       100.0      18.22      23.32      74.20
metric_82803       100.0      18.61      22.90      66.96
metric_82804       100.0      18.65      22.88      69.93
metric_82805       100.0      18.12      23.08      73.36
metric_82806       100.0      18.68      23.17      73.28
metric_82807       100.0      18.99      22.68      65.89
metric_82808       100.0      18.60      22.72      69.95
metric_82809       100.0      18.38      22.76      71.25

--- suggested mapping for config/sites.yaml (check before using) ---
    columns:
      ac_power: null
      poa_irradiance: null
      module_temp: null
      ambient_temp: null
      wind_speed: null
```
