-- RAW: append-only, long format. One row per (file, timestamp, sensor column).
-- Long format means a new sensor or a renamed column never needs a schema change,
-- and every value can be traced back to the file it came from.

CREATE TABLE IF NOT EXISTS SOLARMON.RAW.SITES (
    SYSTEM_ID        INTEGER      NOT NULL PRIMARY KEY,
    NAME             VARCHAR,
    LOCATION         VARCHAR,
    LATITUDE         FLOAT,
    LONGITUDE        FLOAT,
    TIMEZONE         VARCHAR,
    DC_CAPACITY_KW   FLOAT,
    AC_CAPACITY_KW   FLOAT,
    MOUNT            VARCHAR,     -- fixed | single_axis
    TILT             FLOAT,
    AZIMUTH          FLOAT,
    UPDATED_AT       TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

-- Which raw column is which signal, and how to fix its clock and units.
-- Mirrors config/sites.yaml so the warehouse and the Python pipeline agree.
CREATE TABLE IF NOT EXISTS SOLARMON.RAW.SIGNAL_MAP (
    SYSTEM_ID        INTEGER NOT NULL,
    SIGNAL           VARCHAR NOT NULL,  -- ac_power | poa_irradiance | module_temp | ambient_temp | wind_speed
    RAW_COLUMN       VARCHAR NOT NULL,
    UNIT             VARCHAR,           -- NULL = already SI; else F | mph | km/h | W
    PRIMARY KEY (SYSTEM_ID, SIGNAL, RAW_COLUMN)
);

CREATE TABLE IF NOT EXISTS SOLARMON.RAW.FILE_CLOCKS (
    SYSTEM_ID        INTEGER NOT NULL,
    FILE_PATTERN     VARCHAR NOT NULL,  -- substring of the file name, as in sites.yaml
    IS_UTC           BOOLEAN DEFAULT FALSE,
    OFFSET_HOURS     FLOAT   DEFAULT 0,
    PRIMARY KEY (SYSTEM_ID, FILE_PATTERN)
);

CREATE TABLE IF NOT EXISTS SOLARMON.RAW.READINGS (
    SYSTEM_ID        INTEGER       NOT NULL,
    SOURCE_FILE      VARCHAR       NOT NULL,
    MEASURED_ON      TIMESTAMP_NTZ NOT NULL,  -- as logged, before any clock fix
    RAW_COLUMN       VARCHAR       NOT NULL,
    VALUE            FLOAT,
    LOADED_AT        TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
)
CLUSTER BY (SYSTEM_ID, TO_DATE(MEASURED_ON));


-- STAGING: one row per site per 15-minute interval, canonical signals, SI units,
-- every file on the site's local clock. Equivalent to solarmon.load.load_site.
CREATE OR REPLACE VIEW SOLARMON.STAGING.INTERVALS AS
WITH fixed AS (
    SELECT
        r.SYSTEM_ID,
        m.SIGNAL,
        r.RAW_COLUMN,
        -- 1) UTC files -> site local time, 2) fixed clock offsets
        DATEADD('minute', COALESCE(fc.OFFSET_HOURS, 0) * 60,
            IFF(COALESCE(fc.IS_UTC, FALSE),
                CONVERT_TIMEZONE('UTC', s.TIMEZONE, r.MEASURED_ON),
                r.MEASURED_ON)) AS LOCAL_TS,
        CASE m.UNIT
            WHEN 'F'    THEN (r.VALUE - 32) * 5 / 9
            WHEN 'mph'  THEN r.VALUE * 0.44704
            WHEN 'km/h' THEN r.VALUE / 3.6
            WHEN 'W'    THEN r.VALUE / 1000
            ELSE r.VALUE
        END AS VALUE
    FROM SOLARMON.RAW.READINGS r
    JOIN SOLARMON.RAW.SIGNAL_MAP m
      ON m.SYSTEM_ID = r.SYSTEM_ID AND m.RAW_COLUMN = r.RAW_COLUMN
    JOIN SOLARMON.RAW.SITES s
      ON s.SYSTEM_ID = r.SYSTEM_ID
    LEFT JOIN SOLARMON.RAW.FILE_CLOCKS fc
      ON fc.SYSTEM_ID = r.SYSTEM_ID AND CONTAINS(r.SOURCE_FILE, fc.FILE_PATTERN)
),
binned AS (
    -- Average each raw column onto the 15-min grid (keeps energy right for power)...
    SELECT SYSTEM_ID, SIGNAL, RAW_COLUMN,
           TIME_SLICE(LOCAL_TS, 15, 'MINUTE', 'START') AS INTERVAL_START,
           AVG(VALUE) AS VALUE
    FROM fixed
    GROUP BY 1, 2, 3, 4
),
combined AS (
    -- ...then combine columns per signal: inverters are summed, sensors averaged
    SELECT SYSTEM_ID, SIGNAL, INTERVAL_START,
           IFF(SIGNAL = 'ac_power', SUM(VALUE), AVG(VALUE)) AS VALUE
    FROM binned
    GROUP BY 1, 2, 3
)
SELECT
    SYSTEM_ID,
    INTERVAL_START,
    MAX(IFF(SIGNAL = 'ac_power',       VALUE, NULL)) AS AC_POWER_KW,
    MAX(IFF(SIGNAL = 'poa_irradiance', VALUE, NULL)) AS POA_IRRADIANCE,
    MAX(IFF(SIGNAL = 'module_temp',    VALUE, NULL)) AS MODULE_TEMP,
    MAX(IFF(SIGNAL = 'ambient_temp',   VALUE, NULL)) AS AMBIENT_TEMP,
    MAX(IFF(SIGNAL = 'wind_speed',     VALUE, NULL)) AS WIND_SPEED
FROM combined
GROUP BY 1, 2;

-- Data-quality view: daylight coverage per site per day, the first thing to check
-- when a site's numbers look wrong.
CREATE OR REPLACE VIEW SOLARMON.STAGING.DAILY_COVERAGE AS
SELECT
    SYSTEM_ID,
    TO_DATE(INTERVAL_START) AS DAY,
    COUNT_IF(POA_IRRADIANCE > 50)                                   AS DAYLIGHT_INTERVALS,
    COUNT_IF(POA_IRRADIANCE > 50 AND AC_POWER_KW IS NOT NULL)
        / NULLIF(COUNT_IF(POA_IRRADIANCE > 50), 0)                  AS POWER_COVERAGE,
    COUNT_IF(AC_POWER_KW > 0 AND POA_IRRADIANCE IS NOT NULL)
        / NULLIF(COUNT_IF(AC_POWER_KW > 0), 0)                      AS IRRADIANCE_COVERAGE
FROM SOLARMON.STAGING.INTERVALS
GROUP BY 1, 2;
