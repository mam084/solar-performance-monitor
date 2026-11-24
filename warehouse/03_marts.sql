-- MARTS: written by solarmon.pipeline (see solarmon.warehouse), read by the app.
-- Column names match solarmon.warehouse.mart_frames exactly.

CREATE TABLE IF NOT EXISTS SOLARMON.MARTS.INTERVAL_PERFORMANCE (
    SYSTEM_ID        INTEGER       NOT NULL,
    INTERVAL_START   TIMESTAMP_NTZ NOT NULL,
    AC_POWER_KW      FLOAT,
    EXPECTED_AC_KW   FLOAT,
    POA_IRRADIANCE   FLOAT,
    AMBIENT_TEMP     FLOAT,
    RUN_ID           VARCHAR       NOT NULL
)
CLUSTER BY (SYSTEM_ID, TO_DATE(INTERVAL_START));

CREATE TABLE IF NOT EXISTS SOLARMON.MARTS.DAILY_PERFORMANCE (
    SYSTEM_ID        INTEGER NOT NULL,
    DAY              DATE    NOT NULL,
    ACTUAL_KWH       FLOAT,   -- productive hours (POA > 200 W/m²), the PI basis
    EXPECTED_KWH     FLOAT,
    PI               FLOAT,   -- actual / expected; ~1.0 healthy
    BASELINE_PI      FLOAT,   -- rolling 75th percentile, flagged days excluded
    DEV              FLOAT,   -- PI / baseline
    POA_KWH_M2       FLOAT,
    ACTUAL_KWH_DAY   FLOAT,   -- whole day
    EXPECTED_KWH_DAY FLOAT,
    DATA_GAP         BOOLEAN,
    FLAG             VARCHAR, -- ok | low | high | outage | capped | stalled | data_gap | no_irradiance | dark
    EVENT_KIND       VARCHAR,
    RUN_ID           VARCHAR NOT NULL,
    PRIMARY KEY (SYSTEM_ID, DAY)
);

CREATE TABLE IF NOT EXISTS SOLARMON.MARTS.EVENTS (
    EVENT_ID         VARCHAR NOT NULL PRIMARY KEY,  -- <system>-<start>-<kind>, stable across reruns
    SYSTEM_ID        INTEGER NOT NULL,
    KIND             VARCHAR NOT NULL,
    LABEL            VARCHAR,
    START_DAY        DATE    NOT NULL,
    END_DAY          DATE    NOT NULL,
    DAYS             INTEGER,
    ACTIVE           BOOLEAN,
    SEVERITY         VARCHAR,
    PI_BEFORE        FLOAT,
    PI_DURING        FLOAT,
    ENERGY_LOST_KWH  FLOAT,
    EST_COST_USD     FLOAT,
    LOSS_PCT         FLOAT,
    EVIDENCE         VARIANT, -- shape features, reason, daily PI
    RUN_ID           VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS SOLARMON.MARTS.TICKETS (
    TICKET_ID        VARCHAR NOT NULL PRIMARY KEY,
    EVENT_ID         VARCHAR NOT NULL,
    SYSTEM_ID        INTEGER NOT NULL,
    KIND             VARCHAR,
    TITLE            VARCHAR,
    PRIORITY         VARCHAR,  -- P1..P4
    BODY             VARIANT,  -- summary, evidence, causes, actions, parts, safety notes
    DRAFTED_BY       VARCHAR,  -- template | claude:<model>
    DRAFTED_AT       TIMESTAMP_NTZ,
    RUN_ID           VARCHAR NOT NULL
);

-- Reviewer decisions: append-only audit log. The app inserts; nothing updates or deletes.
-- Replaces data/processed/<id>/decisions.json, which doesn't survive an app restart.
CREATE TABLE IF NOT EXISTS SOLARMON.MARTS.TICKET_DECISIONS (
    DECISION_ID      VARCHAR       DEFAULT UUID_STRING(),
    TICKET_ID        VARCHAR       NOT NULL,
    STATUS           VARCHAR       NOT NULL,  -- pending_review | approved | rejected
    REVIEWER         VARCHAR       NOT NULL,
    NOTE             VARCHAR,
    EDITS            VARIANT,                 -- fields the reviewer changed
    DECIDED_AT       TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);
GRANT INSERT ON TABLE SOLARMON.MARTS.TICKET_DECISIONS TO ROLE SOLARMON_APP;

CREATE TABLE IF NOT EXISTS SOLARMON.MARTS.PIPELINE_RUNS (
    RUN_ID              VARCHAR NOT NULL PRIMARY KEY,
    SYSTEM_ID           INTEGER NOT NULL,
    SOURCE              VARCHAR,  -- pvdaq | demo | scada
    STARTED_AT          TIMESTAMP_NTZ,
    DATA_START          DATE,
    DATA_END            DATE,
    CALIBRATION_SCALE   FLOAT,
    AC_CAPACITY_KW      FLOAT,
    NRMSE_HEALTHY_PCT   FLOAT,
    N_EVENTS            INTEGER
);

-- Current state of each ticket: latest decision wins, no decision = pending.
CREATE OR REPLACE VIEW SOLARMON.MARTS.TICKET_QUEUE AS
SELECT
    t.*,
    COALESCE(d.STATUS, 'pending_review') AS STATUS,
    d.REVIEWER, d.NOTE AS REVIEW_NOTE, d.EDITS, d.DECIDED_AT
FROM SOLARMON.MARTS.TICKETS t
LEFT JOIN SOLARMON.MARTS.TICKET_DECISIONS d
  ON d.TICKET_ID = t.TICKET_ID
QUALIFY ROW_NUMBER() OVER (PARTITION BY t.TICKET_ID ORDER BY d.DECIDED_AT DESC NULLS LAST) = 1;

-- One row per site: what the fleet overview tab shows.
CREATE OR REPLACE VIEW SOLARMON.MARTS.FLEET_SUMMARY AS
WITH last_day AS (
    SELECT SYSTEM_ID, MAX(DAY) AS LAST_DAY
    FROM SOLARMON.MARTS.DAILY_PERFORMANCE GROUP BY 1
),
pi_30 AS (
    SELECT p.SYSTEM_ID, MEDIAN(p.PI) AS PI_LAST_30D
    FROM SOLARMON.MARTS.DAILY_PERFORMANCE p
    JOIN last_day l ON l.SYSTEM_ID = p.SYSTEM_ID
    WHERE p.DAY > DATEADD('day', -30, l.LAST_DAY)
    GROUP BY 1
),
ev AS (
    SELECT e.SYSTEM_ID,
           COUNT_IF(e.ACTIVE) AS ACTIVE_EVENTS,
           SUM(IFF(e.END_DAY > DATEADD('day', -90, l.LAST_DAY), e.ENERGY_LOST_KWH, 0)) AS ENERGY_LOST_90D_KWH
    FROM SOLARMON.MARTS.EVENTS e
    JOIN last_day l ON l.SYSTEM_ID = e.SYSTEM_ID
    GROUP BY 1
),
q AS (
    SELECT SYSTEM_ID, COUNT_IF(STATUS = 'pending_review') AS TICKETS_PENDING
    FROM SOLARMON.MARTS.TICKET_QUEUE GROUP BY 1
)
SELECT
    s.SYSTEM_ID, s.NAME, s.LOCATION, s.DC_CAPACITY_KW,
    l.LAST_DAY, pi_30.PI_LAST_30D,
    COALESCE(ev.ACTIVE_EVENTS, 0)        AS ACTIVE_EVENTS,
    COALESCE(ev.ENERGY_LOST_90D_KWH, 0)  AS ENERGY_LOST_90D_KWH,
    COALESCE(q.TICKETS_PENDING, 0)       AS TICKETS_PENDING
FROM SOLARMON.RAW.SITES s
LEFT JOIN last_day l ON l.SYSTEM_ID = s.SYSTEM_ID
LEFT JOIN pi_30      ON pi_30.SYSTEM_ID = s.SYSTEM_ID
LEFT JOIN ev         ON ev.SYSTEM_ID = s.SYSTEM_ID
LEFT JOIN q          ON q.SYSTEM_ID = s.SYSTEM_ID;
