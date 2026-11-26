"""How good is the model, and how much is the site leaving on the table?

Two numbers that separate model error from plant behaviour.

**Model error on full-health days.** "Healthy" (no detected event) isn't the same as
full health. A site that often runs a few inverters or strings short has many
impaired days that never cross an alert threshold, and they inflate the model error.
This measures the model only on clear days when the site was at its own best level:
within a few percent of the rolling 90th percentile of clear-day PI (the "envelope").
At site 2107 this is about 4.5% at 15 minutes, against ~10% on all non-event days.

**Chronic shortfall.** On days with no detected event, how much energy fell short of
the envelope: losses too small or too scattered to trigger an alert, added up. At
2107 that's ~6% of output, ~100 MWh a year.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

CLEAR_VARIABILITY = 0.06   # mean 15-min irradiance change / daily peak
FULL_HEALTH_BAND = (0.97, 1.06)  # PI relative to the envelope
ENVELOPE_QUANTILE = 0.9
ENVELOPE_WINDOW = "90D"


def _daily_pi(out: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    day = out.index.normalize()
    poa = out["poa_irradiance"]
    peak = poa.groupby(day).transform("max")
    variability = (poa.diff().abs() / peak).where(poa > 50).groupby(day).mean()
    sun = (poa > 200) & out["ac_power_kw"].notna() & out["expected_ac_kw"].notna()
    pi = (out["ac_power_kw"].where(sun).groupby(day).sum()
          / out["expected_ac_kw"].where(sun).groupby(day).sum()).replace([np.inf, -np.inf], np.nan)
    return pi, variability


def envelope(out: pd.DataFrame) -> pd.Series:
    """Per day: the site's recent best clear-day PI (rolling 90th percentile, past days only)."""
    pi, var = _daily_pi(out)
    clear = pi[(var < CLEAR_VARIABILITY) & pi.between(0.3, 1.6)].dropna()
    env = clear.rolling(ENVELOPE_WINDOW, min_periods=15).quantile(ENVELOPE_QUANTILE).shift(1)
    env = env.reindex(pi.index).ffill().bfill()
    return env.rename("envelope_pi")


def assess(out: pd.DataFrame, daily: pd.DataFrame, price_usd_kwh: float) -> dict:
    """Model error on full-health days, and the chronic shortfall on event-free days."""
    from .expected import rmse_pct

    pi, var = _daily_pi(out)
    env = envelope(out)
    if env.isna().all():
        return {}
    rel = pi / env
    full_days = rel.index[rel.between(*FULL_HEALTH_BAND) & (var < CLEAR_VARIABILITY)]
    day = pd.Series(out.index.normalize(), index=out.index)
    on_full = day.isin(full_days)
    scaled = out["expected_ac_kw"] * day.map(env)
    err_full = rmse_pct(out["ac_power_kw"], scaled, out["poa_irradiance"], only=on_full)

    ok_days = daily.index[daily["flag"] == "ok"] if "flag" in daily else daily.index
    step_h = out.index.to_series().diff().median() / pd.Timedelta(hours=1)
    best = (out["expected_ac_kw"].groupby(out.index.normalize()).sum() * step_h) * env
    act = out["ac_power_kw"].groupby(out.index.normalize()).sum() * step_h
    k = best.index.isin(ok_days) & best.notna() & act.notna() & (best > 0)
    if not k.any():
        return {"nrmse_full_health_pct": round(err_full, 2), "full_health_days": len(full_days)}
    short_kwh = float(best[k].sum() - act[k].sum())
    years = k.sum() / 365.25
    by_year = (1 - act[k].groupby(act[k].index.year).sum() / best[k].groupby(best[k].index.year).sum())
    return {
        "nrmse_full_health_pct": round(float(err_full), 2),
        "full_health_days": int(len(full_days)),
        "chronic_shortfall_pct": round(100 * short_kwh / float(best[k].sum()), 2),
        "chronic_shortfall_mwh_per_year": round(float(short_kwh / years / 1000), 1),
        "chronic_shortfall_usd_per_year": int(round(float(short_kwh / years * price_usd_kwh))),
        "chronic_shortfall_by_year_pct": {int(y): round(100 * v, 1) for y, v in by_year.items()},
    }
