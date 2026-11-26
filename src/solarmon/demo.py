"""Demo dataset: realistic synthetic data for a real fleet site, with known faults injected.

Used when the real PVDAQ files haven't been downloaded yet (e.g. the hosted app), and
as a labelled backtest for the detector: because we inject each fault ourselves, we
know exactly when it started, ended, and what kind it was.

Weather is physics-based: pvlib clear-sky irradiance for the site's real location,
tilt and azimuth, thinned by a day-to-day cloud process, plus seasonal and daily
temperature swings. "Actual" output is the PVWatts model at a healthy-site loss
factor with slow degradation and meter noise, then each fault below is applied.

Usage:
    python -m solarmon.demo 2107        # writes data/raw_demo/2107.parquet
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass

import numpy as np
import pandas as pd
import pvlib

from .config import DATA_DIR, Site, get_site
from .expected import dc_power_kw, inverter_ac_kw

HEALTHY_SCALE = 0.88  # wiring, mismatch, nameplate vs real power
DEGRADATION_PER_YEAR = 0.006


# Per-site climate for the demo weather. p_cloudy_min/max: chance a day is cloudy in the
# clearest / cloudiest season (cloudy_peak_doy marks the cloudiest); temp_mean/swing in °C.
CLIMATE = {
    2107: dict(p_cloudy_min=0.15, p_cloudy_max=0.50, cloudy_peak_doy=15, temp_mean=16, temp_swing=9, ac_kw=705),
    4902: dict(p_cloudy_min=0.35, p_cloudy_max=0.55, cloudy_peak_doy=30, temp_mean=13, temp_swing=12),
    4903: dict(p_cloudy_min=0.35, p_cloudy_max=0.55, cloudy_peak_doy=30, temp_mean=13, temp_swing=12),
    1430: dict(p_cloudy_min=0.20, p_cloudy_max=0.40, cloudy_peak_doy=120, temp_mean=10, temp_swing=12),
    1367: dict(p_cloudy_min=0.05, p_cloudy_max=0.25, cloudy_peak_doy=30, temp_mean=21, temp_swing=12),
}
DEFAULT_CLIMATE = CLIMATE[2107]
TRACKER = dict(axis_azimuth=180, max_angle=60, backtrack=True, gcr=0.35)


@dataclass
class InjectedFault:
    kind: str  # outage | partial_outage | soiling | sensor_fault | curtailment | data_gap | tracker_stall
    start: str
    end: str
    note: str


def default_faults(start: pd.Timestamp, end: pd.Timestamp, system_id: int = 2107) -> list[InjectedFault]:
    """A realistic year-and-a-bit of problems per site, placed relative to the data window."""
    d = lambda days: (start + pd.Timedelta(days=days)).strftime("%Y-%m-%d")  # noqa: E731
    last = end.normalize()
    r = lambda days: (last - pd.Timedelta(days=days)).strftime("%Y-%m-%d")  # noqa: E731
    if system_id == 4902:
        return [
            InjectedFault("outage", d(430), d(430), "Utility feeder outage after a storm"),
            InjectedFault("sensor_fault", d(500), d(506), "Pyranometer cable cut by mowing crew: no irradiance data"),
            InjectedFault("partial_outage", d(620), d(640), "1 of 4 inverters offline (failed IGBT), ~25% loss"),
        ]
    if system_id == 4903:
        return [
            InjectedFault("soiling", d(450), d(500), "Spring tree-pollen film on low-tilt roof modules"),
            InjectedFault("data_gap", d(600), d(601), "Building network switch replaced"),
        ]
    if system_id == 1430:
        return [
            InjectedFault("tracker_stall", d(480), d(495), "Tracker controller fault, rows parked flat"),
            InjectedFault("outage", d(650), d(651), "Inverter over-temperature trip during heat wave"),
        ]
    if system_id == 1367:
        return [
            InjectedFault("sensor_fault", d(400), d(420), "POA pyranometer soiled/drifting, reads ~14% low"),
            InjectedFault("soiling", r(45), r(0), "Desert dust build-up, no rain since late summer"),
        ]
    return [
        InjectedFault("outage", d(400), d(401), "Inverter ground-fault trip, reset by technician on day 2"),
        InjectedFault("partial_outage", d(455), d(470), "1 of 4 inverters offline (failed IGBT), ~25% loss"),
        InjectedFault("soiling", d(520), d(585), "Dry-season dust build-up, cleared by first autumn rain"),
        InjectedFault("sensor_fault", d(610), d(630), "POA pyranometer soiled/drifting, reads ~14% low"),
        InjectedFault("curtailment", d(660), d(667), "Utility export limit at 60% of AC capacity, midday"),
        InjectedFault("data_gap", d(690), d(692), "Data logger cellular modem offline"),
        # Still going at the end of the data, so the queue has something live
        InjectedFault("partial_outage", r(5), r(0), "String combiner fuse blown, ~12% loss"),
    ]


def weather(site: Site, start: str, end: str, seed: int = 7) -> pd.DataFrame:
    """15-min POA irradiance, ambient temperature and wind on the site's local clock."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, end, freq="15min", tz=site.timezone, inclusive="left")
    clim = CLIMATE.get(site.system_id, DEFAULT_CLIMATE)
    loc = pvlib.location.Location(site.latitude, site.longitude, site.timezone, site.elevation_m)
    sp = loc.get_solarposition(idx + pd.Timedelta(minutes=7.5))  # mid-interval sun position
    cs = loc.get_clearsky(idx + pd.Timedelta(minutes=7.5), solar_position=sp)
    poa_clear = _poa(site, sp, cs).to_numpy()
    # Horizontal irradiance: what a tracker parked flat receives
    flat_clear = pvlib.irradiance.get_total_irradiance(
        0, 180, sp["apparent_zenith"], sp["azimuth"], cs["dni"], cs["ghi"], cs["dhi"])["poa_global"].fillna(0).to_numpy()

    days = idx.normalize().unique()
    doy = days.dayofyear.to_numpy()
    # Seasonal cloudiness, e.g. Northern California: cloudy winters, clear dry summers
    lo, hi = clim["p_cloudy_min"], clim["p_cloudy_max"]
    p_cloudy = lo + (hi - lo) * (np.cos(2 * np.pi * (doy - clim["cloudy_peak_doy"]) / 365) + 1) / 2
    state = rng.random(len(days)) < p_cloudy
    cloud_day = np.where(state, rng.uniform(0.25, 0.8, len(days)), rng.uniform(0.9, 1.0, len(days)))
    per_step = pd.Series(cloud_day, index=days).reindex(idx.normalize()).to_numpy()
    # Passing clouds on cloudy days: smooth intraday wobble
    wobble = pd.Series(rng.normal(0, 1, len(idx))).rolling(6, center=True, min_periods=1).mean().to_numpy()
    cloud = np.clip(per_step + (1 - per_step) * 0.6 * wobble, 0.05, 1.05)
    poa = poa_clear * cloud
    poa_flat = flat_clear * cloud

    hour = idx.hour + idx.minute / 60
    season = -np.cos(2 * np.pi * (idx.dayofyear - 20) / 365)  # -1 midwinter, +1 midsummer
    amb = clim["temp_mean"] + clim["temp_swing"] * season + (7 + 3 * season) * np.sin(2 * np.pi * (hour - 9) / 24) + rng.normal(0, 0.8, len(idx))
    wind = np.clip(2.5 + 1.5 * np.sin(2 * np.pi * (hour - 11) / 24) + rng.normal(0, 0.7, len(idx)), 0.2, None)
    out = pd.DataFrame({"poa_irradiance": poa, "ambient_temp": amb, "wind_speed": wind,
                        "poa_flat": poa_flat}, index=idx.tz_localize(None))
    return out[~out.index.duplicated()]  # the repeated hour when clocks fall back, as load.py does


def _poa(site: Site, sp: pd.DataFrame, cs: pd.DataFrame) -> pd.Series:
    """Clear-sky plane-of-array irradiance for a fixed array or a single-axis tracker."""
    if site.mount == "single_axis":
        trk = pvlib.tracking.singleaxis(sp["apparent_zenith"], sp["azimuth"], **TRACKER)
        tilt, azim = trk["surface_tilt"].fillna(0), trk["surface_azimuth"].fillna(180)
    else:
        tilt, azim = site.tilt, site.azimuth
    return pvlib.irradiance.get_total_irradiance(
        tilt, azim, sp["apparent_zenith"], sp["azimuth"], cs["dni"], cs["ghi"], cs["dhi"])["poa_global"].fillna(0)


def make_demo(site: Site, start: str = "2023-01-01", end: str = "2025-01-01",
              faults: list[InjectedFault] | None = None, seed: int = 7) -> tuple[pd.DataFrame, list[InjectedFault]]:
    """Synthetic 15-min frame in the same shape `load_site` returns, plus the ground truth."""
    rng = np.random.default_rng(seed + 1)
    df = weather(site, start, end, seed)
    faults = faults if faults is not None else default_faults(df.index[0], df.index[-1], site.system_id)
    clim = CLIMATE.get(site.system_id, DEFAULT_CLIMATE)
    ac_cap = site.ac_capacity_kw or clim.get("ac_kw") or site.metered_dc_kw / 1.25

    years = (df.index - df.index[0]) / pd.Timedelta(days=365.25)
    health = HEALTHY_SCALE * (1 - DEGRADATION_PER_YEAR * np.asarray(years))
    dc = dc_power_kw(df, site) * health
    measured_poa = df["poa_irradiance"].copy()
    day = df.index.normalize()

    for f in faults:
        win = (day >= pd.Timestamp(f.start)) & (day <= pd.Timestamp(f.end))
        if f.kind == "partial_outage":
            frac = 0.25 if "inverter" in f.note else 0.12
            dc[win] *= 1 - frac
        elif f.kind == "soiling":
            # Loss grows ~0.25%/day, then a rain washes it off at the end
            progress = (df.index[win] - df.index[win][0]) / pd.Timedelta(days=1)
            dc[win] *= 1 - 0.0025 * np.asarray(progress)
        elif f.kind == "sensor_fault":
            if "no irradiance" in f.note:
                measured_poa[win] = np.nan
            else:
                measured_poa[win] *= 0.86
        elif f.kind == "tracker_stall":
            # Rows parked flat: the array sees horizontal irradiance, the (separate) POA sensor doesn't
            stalled = df.loc[win, ["poa_flat", "ambient_temp", "wind_speed"]].rename(
                columns={"poa_flat": "poa_irradiance"})
            dc[win] = (dc_power_kw(stalled, site) * health[np.asarray(win)]).to_numpy()
        elif f.kind == "outage":
            dc[win] = 0.0

    ac = inverter_ac_kw(dc, ac_cap).to_numpy().copy()
    for f in faults:
        win = (day >= pd.Timestamp(f.start)) & (day <= pd.Timestamp(f.end))
        if f.kind == "curtailment":
            midday = win & (df.index.hour >= 10) & (df.index.hour < 16)
            ac[midday] = np.minimum(ac[midday], 0.6 * ac_cap)
    # Real model error isn't white noise: there are day-to-day misses (spectrum, soiling
    # of the reference cell, snow, angle of incidence) and a seasonal bias, plus meter jitter
    n_days = len(day.unique())
    daily_err = pd.Series(rng.normal(0, 0.02, n_days), index=day.unique()).reindex(day).to_numpy()
    seasonal = 0.015 * np.sin(2 * np.pi * (df.index.dayofyear - 80) / 365)
    ac = ac * (1 + daily_err + seasonal) * rng.normal(1, 0.015, len(ac))
    ac = np.where(df["poa_irradiance"] > 1, ac, 0.0)

    out = pd.DataFrame({
        "poa_irradiance": measured_poa,
        "ambient_temp": df["ambient_temp"],
        "wind_speed": df["wind_speed"],
        "ac_power_kw": np.clip(ac, 0, None),
    }, index=df.index)
    for f in faults:
        if f.kind == "data_gap":
            win = (day >= pd.Timestamp(f.start)) & (day <= pd.Timestamp(f.end))
            out.loc[win, "ac_power_kw"] = np.nan
    return out, faults


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("system_id", type=int, nargs="?", default=2107)
    args = p.parse_args(argv)
    site = get_site(args.system_id)
    df, faults = make_demo(site)
    dest = DATA_DIR / "raw_demo"
    dest.mkdir(parents=True, exist_ok=True)
    df.to_parquet(dest / f"{site.system_id}.parquet")
    pd.DataFrame([f.__dict__ for f in faults]).to_csv(dest / f"{site.system_id}_faults.csv", index=False)
    print(f"wrote {len(df):,} rows and {len(faults)} injected faults to {dest}")


if __name__ == "__main__":
    main()
