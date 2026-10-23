"""Offline tests on synthetic data, so the pipeline is checked without downloading anything."""

import numpy as np
import pandas as pd
import pvlib
import pytest

from solarmon import config, ingest, load
from solarmon.config import Site
from solarmon.expected import expected_ac_kw, pvwatts_ac_kw, rmse_pct
from solarmon.inspect import guess
from solarmon.metrics import daily_performance


@pytest.fixture
def site(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    return Site(
        system_id=9999, name="Synthetic", location="Testville", source="basic",
        latitude=33.0, longitude=-117.0, elevation_m=100, timezone="America/Los_Angeles",
        dc_capacity_kw=100.0, mount="fixed", tilt=20, azimuth=180, years_available=[2020, 2020],
    )


def synthetic_frame(site, days=90, true_scale=0.92, outage_day=70, seed=0):
    """Clear-sky weather plus a 'real' output that is 92% of PVWatts, with one outage day."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2020-04-01", periods=days * 96, freq="15min", tz=site.timezone)
    loc = pvlib.location.Location(site.latitude, site.longitude, site.timezone, site.elevation_m)
    cs = loc.get_clearsky(idx)
    sp = loc.get_solarposition(idx)
    poa = pvlib.irradiance.get_total_irradiance(
        site.tilt, site.azimuth, sp["apparent_zenith"], sp["azimuth"], cs["dni"], cs["ghi"], cs["dhi"]
    )["poa_global"]
    clouds = rng.uniform(0.6, 1.0, days).repeat(96)  # day-to-day cloudiness
    df = pd.DataFrame({
        "poa_irradiance": poa.fillna(0).values * clouds,
        "ambient_temp": 20 + 8 * np.sin(np.linspace(0, days * 2 * np.pi, len(idx))),
        "wind_speed": 2.0,
    }, index=idx)
    model = pvwatts_ac_kw(df, site)
    df["ac_power_kw"] = model * true_scale * rng.normal(1, 0.02, len(idx))
    outage = df.index.normalize() == df.index.normalize().unique()[outage_day]
    df.loc[outage, "ac_power_kw"] = 0.0
    return df


def test_calibration_recovers_true_scale(site):
    df = synthetic_frame(site)
    out = expected_ac_kw(df, site, reference=slice("2020-04-01", "2020-05-15"))
    assert out.attrs["scale"] == pytest.approx(0.92, abs=0.01)
    healthy = out.loc["2020-04-01":"2020-06-05"]  # before the injected outage day
    assert rmse_pct(healthy["ac_power_kw"], healthy["expected_ac_kw"], healthy["poa_irradiance"]) < 5


def test_daily_pi_flags_outage(site):
    df = synthetic_frame(site, outage_day=70)
    daily = daily_performance(expected_ac_kw(df, site))
    healthy = daily["pi"].drop(daily.index[70])
    assert healthy.between(0.95, 1.05).all()
    assert daily["pi"].iloc[70] < 0.05


def test_data_gap_is_not_scored_as_underperformance(site):
    df = synthetic_frame(site)
    gap_day = df.index.normalize() == df.index.normalize().unique()[30]
    df.loc[gap_day, "ac_power_kw"] = np.nan
    daily = daily_performance(expected_ac_kw(df, site))
    assert daily["data_gap"].iloc[30]
    assert np.isnan(daily["pi"].iloc[30])


def test_load_wide_csv_sums_inverters_and_converts_watts(site):
    raw = site.raw_dir / "year=2020" / "month=4" / "day=1"
    raw.mkdir(parents=True)
    ts = pd.date_range("2020-04-01 10:00", periods=4, freq="15min")
    pd.DataFrame({
        "measured_on": ts,
        "inv1_ac_power_w": [40_000.0] * 4,
        "inv2_ac_power_w": [35_000.0] * 4,
        "poa_irradiance_o_1": [800.0] * 4,
    }).to_csv(raw / "day.csv", index=False)
    df = load.load_site(site, {"ac_power": ["inv1_ac_power_w", "inv2_ac_power_w"],
                               "poa_irradiance": "poa_irradiance_o_1"})
    assert df["ac_power_kw"].iloc[0] == pytest.approx(75.0)
    assert df["poa_irradiance"].iloc[0] == 800.0


def test_load_long_parquet_pivots(site):
    raw = site.raw_dir / "year=2020" / "month=4" / "day=2"
    raw.mkdir(parents=True)
    ts = pd.date_range("2020-04-02 10:00", periods=2, freq="15min")
    pd.DataFrame({
        "measured_on": list(ts) * 2,
        "metric_id": [11, 11, 22, 22],
        "value": [50.0, 52.0, 700.0, 710.0],
    }).to_parquet(raw / "day.parquet")
    df = load.load_site(site, {"ac_power": "metric_11", "poa_irradiance": "metric_22"})
    assert list(df["ac_power_kw"]) == [50.0, 52.0]


def test_guess_mapping():
    cols = ["inv_01_ac_power_inv_150", "inv_01_dc_power_inv_151", "poa_irradiance_o_149574",
            "module_temp_1_o_149575", "ambient_temp_o_149576", "wind_speed_o_149577"]
    g = guess(cols)
    assert g["ac_power"] == ["inv_01_ac_power_inv_150"]
    assert g["poa_irradiance"] == ["poa_irradiance_o_149574"]
    assert g["module_temp"] == ["module_temp_1_o_149575"]


def test_partition_parsing_and_local_paths(site):
    key = "pvdaq/parquet/pvdata/system_id=9999/year=2016/month=3/day=7/system_9999__date_2016_03_07.parquet"
    assert str(ingest.partition_date(key)) == "2016-03-07"
    assert ingest.local_path(site, key) == site.raw_dir / "year=2016/month=3/day=7/system_9999__date_2016_03_07.parquet"


def test_load_aligns_mixed_intervals(site):
    """1-min irradiance and 15-min meter files should merge onto one 15-min grid."""
    site.raw_dir.mkdir(parents=True)
    t1 = pd.date_range("2020-04-01 10:00", periods=30, freq="1min")
    pd.DataFrame({"measured_on": t1, "poa_irradiance_o_1": range(30)}).to_csv(
        site.raw_dir / "irradiance.csv", index=False)
    t15 = pd.date_range("2020-04-01 10:00", periods=2, freq="15min")
    pd.DataFrame({"measured_on": t15, "meter_power_kw": [60.0, 62.0]}).to_csv(
        site.raw_dir / "meter.csv", index=False)
    df = load.load_site(site, {"ac_power": "meter_power_kw", "poa_irradiance": "poa_irradiance_o_1"})
    assert len(df) == 2
    assert df["poa_irradiance"].tolist() == [7.0, 22.0]  # mean of minutes 0-14 and 15-29
    assert df["ac_power_kw"].tolist() == [60.0, 62.0]


def test_load_finds_alternate_timestamp_column(site):
    site.raw_dir.mkdir(parents=True)
    ts = pd.date_range("2020-04-01 10:00", periods=2, freq="15min")
    pd.DataFrame({"Timestamp": ts, "meter_power_kw": [60.0, 62.0], "poa_w_m2": [800.0, 810.0]}).to_csv(
        site.raw_dir / "meter_2025.csv", index=False)
    df = load.load_site(site, {"ac_power": "meter_power_kw", "poa_irradiance": "poa_w_m2"})
    assert df["ac_power_kw"].tolist() == [60.0, 62.0]


def test_peek_reports_unparseable_file_instead_of_crashing(site):
    site.raw_dir.mkdir(parents=True)
    pd.DataFrame({"a": [1], "b": [2]}).to_csv(site.raw_dir / "weird.csv", index=False)
    out = load.peek(site)
    assert isinstance(next(iter(out.values())), KeyError)


def test_interval_end_timestamps_and_unit_conversion(site):
    """Interval-end stamps shift back one step; °F and mph convert to °C and m/s."""
    site.raw_dir.mkdir(parents=True)
    site.timestamps = "end"
    site.units = {"ambient_temp": "F", "wind_speed": "mph"}
    t15 = pd.date_range("2020-04-01 10:15", periods=2, freq="15min")
    pd.DataFrame({"measured_on": t15, "meter_kw": [60.0, 62.0], "amb": [50.0, 68.0], "wind": [10.0, 10.0]}).to_csv(
        site.raw_dir / "meter.csv", index=False)
    t5 = pd.date_range("2020-04-01 10:05", periods=6, freq="5min")
    pd.DataFrame({"measured_on": t5, "poa": [100.0, 200, 300, 400, 500, 600]}).to_csv(
        site.raw_dir / "irr.csv", index=False)
    df = load.load_site(site, {"ac_power": "meter_kw", "poa_irradiance": "poa",
                               "ambient_temp": "amb", "wind_speed": "wind"})
    assert str(df.index[0].time()) == "10:00:00"
    assert df["poa_irradiance"].tolist() == [200.0, 500.0]  # 10:05-10:15 and 10:20-10:30 stamps
    assert df["ac_power_kw"].tolist() == [60.0, 62.0]
    assert df["ambient_temp"].tolist() == pytest.approx([10.0, 20.0])
    assert df["wind_speed"].iloc[0] == pytest.approx(4.4704)


def test_guess_finds_meter_output_column():
    assert guess(["meter_revenue_grade_ac_output_meter_149578"])["ac_power"] == [
        "meter_revenue_grade_ac_output_meter_149578"]


def test_lag_scan_finds_injected_offset(site):
    from solarmon.qa import lag_scan
    df = synthetic_frame(site, days=30, outage_day=29)
    shifted = df.copy()
    shifted["poa_irradiance"] = df["poa_irradiance"].shift(4)  # POA stamps 1 hour late
    assert lag_scan(df, max_hours=3).loc["all", "best_lag_h"] == 0.0
    assert lag_scan(shifted, max_hours=3).loc["all", "best_lag_h"] == 1.0


def test_clean_removes_impossible_values(site):
    from solarmon.qa import clean
    df = pd.DataFrame({"ac_power_kw": [50.0, 500.0, -2.0], "poa_irradiance": [800.0, 2000.0, -5.0]})
    out = clean(df, site)  # site is 100 kW
    assert out["ac_power_kw"].tolist()[0] == 50.0 and np.isnan(out["ac_power_kw"][1])
    assert out["ac_power_kw"][2] == 0.0
    assert np.isnan(out["poa_irradiance"][1]) and out["poa_irradiance"][2] == 0.0


def test_default_reference_skips_period_without_irradiance(site):
    df = synthetic_frame(site, days=120, outage_day=110)
    df.loc[:"2020-05-10", "poa_irradiance"] = np.nan  # irradiance sensor comes online later
    out = expected_ac_kw(df, site)
    assert out.attrs["reference"][0].startswith("2020-05-11")
    assert out.attrs["scale"] == pytest.approx(0.92, abs=0.01)


def test_utc_file_converted_to_local_and_flagged_by_file_timing(site):
    """A UTC-logged file lands on the local clock; file_timing confirms it peaks near noon."""
    from solarmon.qa import file_timing
    site.raw_dir.mkdir(parents=True)
    df = synthetic_frame(site, days=20, outage_day=19)
    local = df.index.tz_localize(None)
    utc = df.index.tz_convert("UTC").tz_localize(None)
    pd.DataFrame({"measured_on": local, "meter_kw": df["ac_power_kw"].values}).to_csv(
        site.raw_dir / "meter.csv", index=False)
    pd.DataFrame({"measured_on": utc, "poa": df["poa_irradiance"].values}).to_csv(
        site.raw_dir / "irradiance_2024.csv", index=False)
    site.columns = {"ac_power": "meter_kw", "poa_irradiance": "poa"}

    t = file_timing(site)
    assert t.loc[("irradiance_2024.csv", "poa_irradiance"), "looks_right"] == "CHECK"

    site.utc_files = ["irradiance_2024"]
    t = file_timing(site)
    assert (t["looks_right"] == "yes").all()
    out = load.load_site(site)
    assert out["ac_power_kw"].corr(out["poa_irradiance"]) > 0.95
