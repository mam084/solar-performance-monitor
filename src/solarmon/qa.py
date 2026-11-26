"""Data quality checks: physical-limit cleaning and timestamp alignment diagnostics."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pvlib

from .config import Site
from .load import load_file, raw_files


def clean(df: pd.DataFrame, site: Site) -> pd.DataFrame:
    """Remove physically impossible values (they become NaN, i.e. missing).

    - AC power above 1.2x DC nameplate (meter spikes) or below a small standby draw
    - POA irradiance above 1,500 W/m² (no sensor reads that legitimately) or negative
    """
    out = df.copy()
    if "ac_power_kw" in out:
        p = out["ac_power_kw"]
        out["ac_power_kw"] = p.where(p <= 1.2 * site.metered_dc_kw).clip(lower=0)
    if "poa_irradiance" in out:
        g = out["poa_irradiance"]
        out["poa_irradiance"] = g.where(g <= 1500).clip(lower=0)
    return out


def _lag_corr(power: pd.Series, poa: pd.Series, lags: range, step: pd.Timedelta) -> pd.Series:
    """corr(power[t], poa[t + lag]) for each lag (in steps), over times when either is non-trivial."""
    res = {}
    for k in lags:
        shifted = poa.shift(-k)
        m = power.notna() & shifted.notna() & ((power > 1) | (shifted > 20))
        res[k * step / pd.Timedelta(hours=1)] = power[m].corr(shifted[m]) if m.sum() > 100 else np.nan
    return pd.Series(res, name="corr")


def lag_scan(df: pd.DataFrame, max_hours: float = 12, by: str | None = None) -> pd.DataFrame:
    """Find the time shift (hours) that best lines up power with irradiance.

    Positive best_lag_h means irradiance happens *later* than power at the same stamp,
    i.e. the irradiance clock runs behind and should be shifted earlier by that many hours.

    by: None for the whole record, "year" to check each year separately (catches files
        with different time bases), "month" to pinpoint exactly when an offset starts
        and stops, or "dst" to compare summer vs winter (catches a daylight-saving
        mismatch between files).
    """
    step = df.index.to_series().diff().mode().iloc[0]
    n = int(pd.Timedelta(hours=max_hours) / step)
    lags = range(-n, n + 1)

    if by is None:
        groups = {"all": df}
    elif by == "year":
        groups = dict(tuple(df.groupby(df.index.year)))
    elif by == "month":
        groups = dict(tuple(df.groupby(df.index.strftime("%Y-%m"))))
    elif by == "dst":
        summer = df.index.month.isin([4, 5, 6, 7, 8, 9, 10])
        groups = {"Apr–Oct (DST)": df[summer], "Nov–Mar (standard)": df[~summer]}
    else:
        raise ValueError("by must be None, 'year', 'month' or 'dst'")

    rows = []
    for name, g in groups.items():
        # Shift on the full grid so a lag moves by clock time, not by row count
        g = g.asfreq(step)
        c = _lag_corr(g["ac_power_kw"], g["poa_irradiance"], lags, step)
        if c.notna().any():
            rows.append({"group": name, "best_lag_h": c.idxmax(), "corr_at_best": c.max(),
                         "corr_at_zero": c.get(0.0, np.nan), "points": int(g["ac_power_kw"].notna().sum())})
    return pd.DataFrame(rows).set_index("group").round(3)


def hourly_profile(df: pd.DataFrame) -> pd.DataFrame:
    """Average power and irradiance by hour of day, each scaled to its own peak.

    If timestamps line up, the two curves should peak at the same hour and overlap.
    """
    h = df.groupby(df.index.hour)[["ac_power_kw", "poa_irradiance"]].mean()
    return h / h.max()


def solar_noon_h(index: pd.DatetimeIndex, site: Site) -> float:
    """Average local clock time (hours) of solar noon over the days in `index`, DST-aware."""
    days = pd.DatetimeIndex(index.normalize().unique())
    if len(days) == 0:
        return np.nan
    eot_min = pvlib.solarposition.equation_of_time_spencer71(days.dayofyear)
    utc_offset_h = np.array([d.tz_localize(site.timezone, nonexistent="shift_forward",
                                           ambiguous=False).utcoffset().total_seconds() / 3600
                             for d in days])
    noon = 12 - site.longitude / 15 - np.asarray(eot_min) / 60 + utc_offset_h
    return float(np.mean(noon))


def file_timing(site: Site) -> pd.DataFrame:
    """When does each file's signal peak, on the clock the loader puts it on?

    Checks every raw file against the sun, so a file on the wrong clock (e.g. UTC)
    stands out on its own instead of being averaged in with correct files.

    For sunlight-driven signals (power, POA), `centroid_h` is the energy-weighted
    average time of the daily curve, which should sit near solar noon for the
    file's dates (`solar_noon_h`, local clock). `offset_h` is the difference; more
    than ~0.75 h either way is flagged. Air temperature and wind have no sharp
    solar anchor, so they're checked by peak hour (mid-afternoon is normal).
    """
    by_raw = {}
    for name, src in site.columns.items():
        for c in ([src] if isinstance(src, str) else (src or [])):
            by_raw[c] = name
    rows = []
    for path in raw_files(site):
        f = load_file(site, path, set(by_raw))
        if f.empty:
            continue
        noon = solar_noon_h(f.index, site)
        for col in f.columns:
            name = by_raw[col]
            # Hour buckets: value at h covers h..h+1, so its centre is h + 0.5
            prof = f[col].groupby(f.index.hour + 0.5).mean()
            sun = name in ("ac_power", "poa_irradiance")
            if sun:
                w = prof.clip(lower=0)
                # Circular mean: a curve shifted past midnight wraps around instead of
                # being averaged across the whole day
                ang = 2 * np.pi * np.asarray(w.index) / 24
                if w.sum() > 0:
                    c = np.arctan2((w * np.sin(ang)).sum(), (w * np.cos(ang)).sum())
                    centroid = float(c * 24 / (2 * np.pi) % 24)
                else:
                    centroid = np.nan
                offset = (centroid - noon + 12) % 24 - 12  # signed, within ±12 h
                ok = abs(offset) <= 0.75
            else:
                centroid = offset = np.nan
                ok = 13 <= int(prof.idxmax()) <= 18
            rows.append({
                "file": path.name, "signal": name,
                "dates": f"{f.index.min():%Y-%m-%d} to {f.index.max():%Y-%m-%d}",
                "peak_hour": int(prof.idxmax()), "centroid_h": round(centroid, 2),
                "solar_noon_h": round(noon, 2) if sun else np.nan,
                "offset_h": round(offset, 2), "looks_right": "yes" if ok else "CHECK",
            })
    return pd.DataFrame(rows).set_index(["file", "signal"])


def trim_to_sensor_start(df: pd.DataFrame, min_coverage: float = 0.8) -> pd.DataFrame:
    """Drop the stretch before the irradiance sensor came online.

    Some sites logged power for months before their irradiance sensor was installed
    (site 2107: all of 2017 until November). That period can't be modelled, and left in
    it reads as one long sensor fault. A new sensor also tends to report patchily for a
    while, so this waits for sustained coverage: the first 30 days in which irradiance is
    present for at least `min_coverage` of the daylight intervals (those with power).
    """
    producing = df["ac_power_kw"] > 0.02 * df["ac_power_kw"].quantile(0.99)
    have = df["poa_irradiance"].notna()[producing]
    cov = have.groupby(have.index.normalize()).mean().asfreq("D").rolling(30, min_periods=20).mean()
    ok = cov[cov >= min_coverage]
    if ok.empty:
        return df
    start = ok.index[0] - pd.Timedelta(days=29)
    out = df.loc[start:]
    out.attrs = dict(df.attrs, trimmed_before=str(start.date()) if start > df.index[0] else None)
    return out


def seasonal_clock(df: pd.DataFrame, site) -> dict:
    """Where the day's output centre falls vs solar noon, split by daylight-saving season.

    For sites with thousands of daily files, per-file checks are noise (cloudy days move
    the peak). Monthly medians aren't. A logger on standard time all year shows about
    -1 h while daylight saving is in force and 0 h otherwise.
    """
    import pvlib
    loc = pvlib.location.Location(site.latitude, site.longitude, site.timezone)
    rows = []
    for (y, mo), g in df.groupby([df.index.year, df.index.month]):
        if len(g) < 96 * 10 or g["poa_irradiance"].clip(lower=0).sum() <= 0:
            continue
        h = np.asarray(g.index.hour + g.index.minute / 60 + 7.5 / 60)
        w = g["poa_irradiance"].clip(lower=0).fillna(0).to_numpy()
        centre = float((w * h).sum() / w.sum())
        mid = pd.date_range(pd.Timestamp(year=y, month=mo, day=15), periods=96, freq="15min", tz=site.timezone)
        el = loc.get_solarposition(mid + pd.Timedelta(minutes=7.5))["apparent_elevation"].clip(lower=0)
        hh = np.asarray(mid.hour + mid.minute / 60 + 7.5 / 60)
        noon = float((el.to_numpy() * hh).sum() / el.to_numpy().sum())
        dst = pd.Timestamp(year=y, month=mo, day=15).tz_localize(site.timezone).dst() != pd.Timedelta(0)
        rows.append((dst, centre - noon))
    t = pd.DataFrame(rows, columns=["dst", "offset"])
    return {"dst_h": float(t.loc[t.dst, "offset"].median()) if t.dst.any() else float("nan"),
            "standard_h": float(t.loc[~t.dst, "offset"].median()) if (~t.dst).any() else float("nan"),
            "months": len(t)}
