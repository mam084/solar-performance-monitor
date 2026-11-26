"""Preflight on raw files laid out like site 2107's real ones (meter, UTC irradiance, environment)."""

import dataclasses

import pandas as pd
import pytest

from solarmon import config
from solarmon.config import get_site
from solarmon.demo import make_demo
from solarmon.preflight import FAIL, PASS, WARN, report, run


@pytest.fixture
def site(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    return dataclasses.replace(get_site(2107), utc_files=[], file_offsets_h={})


def write_raw(site, days=150):
    df, _ = make_demo(site, start="2023-03-01", end=str((pd.Timestamp("2023-03-01") + pd.Timedelta(days=days)).date()),
                      faults=[], seed=5)
    c = site.columns
    d = site.raw_dir / "data"
    d.mkdir(parents=True)
    local = df.index
    pd.DataFrame({"measured_on": local, c["ac_power"]: df["ac_power_kw"].values}).to_csv(
        d / "2107_meter_15m_data.csv", index=False)
    utc = local.tz_localize(site.timezone, ambiguous="NaT", nonexistent="NaT").tz_convert("UTC").tz_localize(None)
    pd.DataFrame({"measured_on": utc, c["poa_irradiance"]: df["poa_irradiance"].values}).dropna().to_csv(
        d / "2107_irradiance_15m_data_2025.csv", index=False)
    pd.DataFrame({"measured_on": local, c["ambient_temp"]: df["ambient_temp"].values * 9 / 5 + 32,
                  c["wind_speed"]: df["wind_speed"].values / 0.44704}).to_csv(
        d / "2107_environment_data.csv", index=False)


def statuses(checks):
    return {c.name: c.status for c in checks}


def test_no_files_tells_you_to_download(site):
    checks, _ = run(site)
    assert checks[0].status == FAIL and "ingest download" in checks[0].fix


def test_utc_file_is_caught_and_the_fix_named(site):
    write_raw(site)
    checks, _ = run(site)
    clock = [c for c in checks if c.name == "file clocks"]
    assert clock and clock[0].status == WARN
    assert "utc_files" in clock[0].fix and "irradiance_15m_data_2025" in clock[0].fix


def test_correct_config_is_ready(site):
    write_raw(site)
    site.utc_files = ["irradiance_15m_data_2025"]
    checks, _ = run(site)
    s = statuses(checks)
    assert all(v == PASS for v in s.values()), report(site, checks)
    assert "Ready" in report(site, checks)


def test_long_format_basic_site_columns_are_found(tmp_path, monkeypatch):
    """Basic PVDAQ sites store one row per (timestamp, metric_id, value)."""
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    site = dataclasses.replace(get_site(4902))
    idx = pd.date_range("2016-06-03", periods=96, freq="15min")
    rows = []
    for col, val in site.mapped_columns.items():
        mid = int(val.split("_")[1])
        rows.append(pd.DataFrame({"measured_on": idx, "metric_id": mid, "value": 1.0}))
    d = site.raw_dir / "year=2016" / "month=6" / "day=3"
    d.mkdir(parents=True)
    pd.concat(rows).to_parquet(d / "system_4902__date_2016_06_03.parquet")
    from solarmon.preflight import _columns_in
    assert set(site.mapped_columns.values()) <= _columns_in(d / "system_4902__date_2016_06_03.parquet")
