"""Data quality checks: physical-limit cleaning and timestamp alignment diagnostics."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .config import Site


def clean(df: pd.DataFrame, site: Site) -> pd.DataFrame:
    """Remove physically impossible values (they become NaN, i.e. missing).

    - AC power above 1.2x DC nameplate (meter spikes) or below a small standby draw
    - POA irradiance above 1,500 W/m² (no sensor reads that legitimately) or negative
    """
    out = df.copy()
    if "ac_power_kw" in out:
        p = out["ac_power_kw"]
        out["ac_power_kw"] = p.where(p <= 1.2 * site.dc_capacity_kw).clip(lower=0)
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
        with different time bases), or "dst" to compare summer vs winter (catches a
        daylight-saving mismatch between files).
    """
    step = df.index.to_series().diff().mode().iloc[0]
    n = int(pd.Timedelta(hours=max_hours) / step)
    lags = range(-n, n + 1)

    if by is None:
        groups = {"all": df}
    elif by == "year":
        groups = dict(tuple(df.groupby(df.index.year)))
    elif by == "dst":
        summer = df.index.month.isin([4, 5, 6, 7, 8, 9, 10])
        groups = {"Apr–Oct (DST)": df[summer], "Nov–Mar (standard)": df[~summer]}
    else:
        raise ValueError("by must be None, 'year' or 'dst'")

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
