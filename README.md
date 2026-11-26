# Solar Performance Monitor

Compares each solar site's **actual** output with the output its **weather says it should have produced**, flags underperformance, and has an AI agent draft maintenance tickets for a human to approve.

Built on NREL's public [PVDAQ](https://data.openei.org/submissions/4568) dataset: real production and on-site weather sensor data from PV systems across the US.

> **Status: v0.4.** The full loop runs end to end: physics baseline, ML residual layer, fault detection and classification, agent-drafted tickets, and a Streamlit approval queue. **Four of the five sites run on real PVDAQ data**, refreshed automatically by a scheduled job; site 1367 stays on a labelled **demo dataset** until its irradiance channel can be trusted. See the [roadmap](#roadmap).

| Site | Data | Model error, healthy days | Events | Notes |
|---|---|---|---|---|
| 2107 Farm Solar Array, CA (fixed) | 2017–2025 | 9.9% (ML adopted) | 42 | sensor dropouts; 80-day partial outage in 2025 |
| 4902 NIST Ground, MD (fixed) | 2014–2018 | 7.8% (ML adopted) | 31 | 8 snow events; logger on standard time |
| 4903 NIST Roof, MD (fixed) | 2014–2018 | 4.0% | 20 | 9 snow events |
| 1430 NREL Mesa, CO (tracker) | 2008–2017 | 7.1% | 114 | 41 snow events; one of two inverters metered |
| 1367 Henderson, NV (fixed) | demo | 2.8% | 2 | POA channel unusable, see `config/sites.yaml` |

**What it does on the demo fleet:**

- **Real data:** four sites, 2008–2025. See the table above and [what the real data taught us](docs/scaling.md#what-the-real-data-taught-us)
- **Demo fleet:** 2.6–2.9% nRMSE on healthy days. Backtest over 300 simulated site-years (5 sites × 30 weather seeds × 2 years): **477 of 480** injected faults found, **474** labelled correctly, **4** false alarms. Abrupt faults are flagged the day they start; soiling about 5 weeks in, with the start of the slide traced back
- Recognises seven fault types, including tracker stalls on the single-axis site
- Drafts a maintenance ticket per event (template offline, Claude with an API key). Recent and ongoing events go to the review queue; older ones are filed under History. Every approve / edit / reject is logged with who did it

## Why this problem

An operator running dozens of sites can't eyeball every inverter curve. Production naturally swings with the weather, so "output dropped 20% today" means nothing on its own. A cloudy day and a tripped inverter look the same in raw kWh. The useful question is **"is this site producing what today's sunlight and temperature say it should?"** Answering that per site, per day, at fleet scale is what this project does.

## How it works

```mermaid
flowchart LR
    A[NREL PVDAQ<br/>public S3 bucket] -->|ingest| B[Raw daily files<br/>per site]
    B -->|load + column mapping| C[Clean time series<br/>power, POA irradiance, temps]
    C --> D[Expected output<br/>PVWatts physics model<br/>+ ML residual correction]
    C --> E[Actual output]
    D --> F[Performance index<br/>actual ÷ expected]
    E --> F
    F --> G[Detection<br/>outage, soiling, clipping,<br/>sensor fault]
    G --> H[Agent drafts<br/>maintenance ticket]
    H --> I[Human approves /<br/>edits / rejects]
```

1. **Ingest.** Download a site's files from NREL's public S3 bucket (no AWS account needed).
2. **Expected output.** NREL's PVWatts model (via [`pvlib`](https://pvlib-python.readthedocs.io/)) turns the site's own plane-of-array irradiance and module temperature into an expected AC power. A single scale factor, fit on a known-good reference window, calibrates it to that site's real-world losses. On top of that, an ML residual model (gradient boosting on irradiance, its one-hour average, temperature and sun position) learns what physics misses. Each site gets it **only if it beats physics on held-out data** (the last quarter of the record) on both 15-minute error and daily scatter. Site 2107 adopts it (held-out error 12.2% → 10.3%); the demo sites don't, because there's nothing systematic left to learn.
3. **Performance index (PI).** Daily actual energy ÷ expected energy. A healthy site sits near 1.0 regardless of weather.
4. **Detection.** First, a correction learned from the site's own history (its normal actual/expected ratio by month and half-hour) removes biases that repeat every day, such as a sensor angled differently from the panels. Each day's PI is then compared with a rolling baseline (the median of recent days, recomputed without flagged days so a long fault doesn't become the new normal), with alert thresholds scaled to how noisy that site is. Runs of flagged days become events, classified by shape:

   | Event | Signature |
   |---|---|
   | Full outage | PI near zero |
   | Partial outage | Abrupt step down, then flat (an inverter, string or fuse) |
   | Soiling / gradual loss | Slow slide over weeks, often reset by rain or a wash |
   | Curtailment | Normal mornings and evenings, capped at midday on sunny days |
   | Tracker stall | The reverse: fine at midday, short in the morning and evening (rows parked flat); tracker sites only |
   | Snow cover | Output collapses but trickles on, right after freezing weather; low severity, no dispatch |
   | Irradiance sensor fault | Output *above* what the sensor allows, or no sensor data |
   | Monitoring data gap | No meter readings in daylight |

   Each event carries its evidence: PI before and during, energy lost and estimated cost, and the shape features behind the label.
5. **Ticket agent + approval UI.** Every event gets a draft ticket built from a fixed evidence packet (numbers, dates, shape features and an O&M playbook). With an `ANTHROPIC_API_KEY`, Claude writes the draft through a forced tool call, so the reply always fits the ticket schema and has only the packet's numbers to work from; any failure falls back to the template. Nothing is dispatched until a person approves it in the app, and every decision is logged with the reviewer and what they changed.

## Starter fleet

| ID | Site | Location | Size | Mount | Why it's here |
|---|---|---|---|---|---|
| 2107 | Farm Solar Array | Arbuckle, CA | 893 kW | Fixed, ground | Anchor site: 7 years, 125 sensor channels, passed NREL QA cleanly |
| 4902 | NIST Ground | Gaithersburg, MD | 271 kW | Fixed, ground | Heavily instrumented research array |
| 4903 | NIST Roof | Gaithersburg, MD | 74 kW | Fixed, roof | Same weather as 4902, different mounting |
| 1430 | NREL Mesa | Golden, CO | 721 kW | Single-axis tracker | Tracker physics, high altitude |
| 1367 | Henderson Aquatic Complex | Henderson, NV | 277 kW | Fixed | Hot desert climate |

Site metadata lives in [`config/sites.yaml`](config/sites.yaml).

## Quickstart

```bash
git clone https://github.com/mam084/solar-performance-monitor.git
cd solar-performance-monitor
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 1. See what's available, then download a site (try --dry-run first to check the size)
python -m solarmon.ingest download 2107 --dry-run
python -m solarmon.ingest download 2107 --include meter irradiance environment
python -m solarmon.ingest download 4902 --start 2016-01-01 --end 2016-12-31

# 2. See which sensors the site has and get a suggested column mapping
python -m solarmon.inspect 2107
#    -> copy the right column names into config/sites.yaml

# 3. Explore and build the baseline
jupyter notebook notebooks/01_site_eda.ipynb

# 4. Check the raw data (mapping, file clocks, coverage, calibration), then run the pipeline
python -m solarmon.preflight 2107
python -m solarmon.pipeline build 2107            # add --claude to draft tickets with Claude
streamlit run streamlit_app.py

# No data yet? Build the demo site instead, and backtest the detector
python -m solarmon.pipeline build all --demo
python -m solarmon.backtest --seeds 30 --site all

# Tests run on synthetic data, so no download is needed
pytest
```

## Deploying the app

The app only reads `data/processed/`, which is small and committed, so it deploys as is.

1. On [share.streamlit.io](https://share.streamlit.io), create an app from this repo, branch `main`, file `streamlit_app.py`.
2. Optional: under *Settings → Secrets*, add `ANTHROPIC_API_KEY = "..."` to turn on **Redraft with Claude**.
3. New data arrives on its own: see [Keeping the data current](#keeping-the-data-current).

Approval decisions are saved to `data/processed/<id>/decisions.json`, which is git-ignored. On Streamlit Cloud that file lasts until the app restarts; a durable store is part of phase 4.


## Keeping the data current

Nobody needs to download data by hand. The [`update-data`](.github/workflows/update-data.yml) GitHub Actions job runs daily, and on any push to `main` that changes `config/sites.yaml` or the pipeline code:

1. For every site with a real column mapping, it lists the site's files in NREL's public bucket.
2. It compares a fingerprint of that listing, the site's config and the pipeline code with the one saved at the last build (`data/processed/<id>/source_manifest.json`). If nothing changed, it stops.
3. Otherwise it downloads only the missing files, runs `preflight`, rebuilds, runs the tests and commits `data/processed/`. Streamlit Cloud redeploys from that commit.

A site that fails preflight keeps its previous outputs; preflight warnings show up in the app under the site's chart. To run it now, or force a rebuild, use **Actions → update-data → Run workflow**. The same thing locally: `python -m solarmon.update`.

Onboarding a new site is a config change: add its column mapping to `sites.yaml`, push, and the job builds it. Sites without a mapping stay on demo data.

GitHub pauses scheduled workflows in a repo with no commits for 60 days; re-enable it from the Actions tab if that happens.

## Further reading

- [`docs/scaling.md`](docs/scaling.md): approach, results, and how this runs daily across a full fleet
- [`warehouse/`](warehouse/): Snowflake schema (raw → staging → marts) that `python -m solarmon.warehouse push` loads
- [`.github/workflows/update-data.yml`](.github/workflows/update-data.yml): the scheduled data update (see [Keeping the data current](#keeping-the-data-current))

## Repo layout

```
config/sites.yaml        fleet definition and per-site sensor column mapping
src/solarmon/
  ingest.py              download from NREL's public S3 bucket
  inspect.py             list a site's sensors and suggest a column mapping
  load.py                raw files -> one clean, time-indexed frame per site
  expected.py            PVWatts physics baseline + calibration
  metrics.py             daily performance index
  qa.py                  physical-limit cleaning and timestamp checks
  detect.py              baseline, daily flags, event detection and classification
  tickets.py             evidence packet, template drafter, Claude drafter
  review.py              approve / edit / reject log
  pipeline.py            raw -> expected -> PI -> events -> tickets -> data/processed/
  demo.py                synthetic site history with injected, labelled faults
  backtest.py            detector accuracy over many simulated histories
  preflight.py           checks a site's raw data and names the sites.yaml fix for each problem
  update.py              scheduled update: fingerprint, download, preflight, build; column reports for unmapped sites
  ml.py                  ML residual model with a held-out adoption test
  warehouse.py           shapes outputs into the Snowflake tables and loads them
warehouse/               Snowflake DDL: setup, raw + staging, marts
.github/workflows/       update-data.yml: scheduled data update
docs/scaling.md          scaling and operations write-up
streamlit_app.py         fleet overview, site detail, ticket approval queue
data/processed/          pipeline outputs the app reads (committed, ~1.5 MB per site)
notebooks/               exploration, one notebook per question
tests/                   offline tests on synthetic data
```

## Roadmap

- [ ] **Phase 1: Baseline on one site**
  - [x] Repo, ingestion, and loader for both PVDAQ data layouts
  - [x] PVWatts expected-output model with calibration, plus a daily performance index
  - [x] Validated on the demo site: 2.9% nRMSE on healthy days
  - [x] Real data for site 2107 built by the scheduled job; learned daily-shape correction, sensor-start trim and site-scaled thresholds added after the first run
  - [x] ML residual layer adopted at 2107 on held-out data (12.2% → 10.3% at 15 min)
  - [ ] A second irradiance source (satellite) to cut the remaining point-sensor error
- [ ] **Phase 2: Fleet + detection**
  - [x] Underperformance detection and event classification, backtested on injected faults (477/480 found over 300 site-years)
  - [x] Demo histories for all 5 sites, including single-axis tracker physics
  - [ ] Backtest on real, logged events at site 2107
  - [x] 4 of 5 sites on real data (1367's irradiance channel is unusable)
  - [x] ML residual model (gradient boosting), adopted per site only if it beats physics on held-out data
  - [x] Column reports for unmapped sites written by the update job (`data/processed/<id>/inspect.md`)
- [x] **Phase 3: Ticket agent + approval UI**
  - [x] Claude drafts tickets from flagged events with evidence (template fallback offline)
  - [x] Streamlit approval queue with edit, reject-with-reason, audit history and export
- [ ] **Phase 4: Productionize**
  - [x] Snowflake schema (raw → staging → marts) and loader, column-checked against the DDL in tests
  - [ ] Snowflake as the live store (run `warehouse/*.sql`, then `solarmon.warehouse push all`)
  - [x] Scheduled data update (GitHub Actions): rebuilds only when NREL's files, the site config or the code change
  - [ ] Durable store for approval decisions
  - [x] Write-up on scaling to a full fleet ([`docs/scaling.md`](docs/scaling.md))

## Data

Deline, C., Perry, K., Deceglie, M., Muller, M., Sekulic, W., & Jordan, D. (2021). *Photovoltaic Data Acquisition (PVDAQ) Public Datasets* [Data set]. Open Energy Data Initiative (OEDI), NREL. https://doi.org/10.25984/1846021. Licensed CC BY 4.0.
