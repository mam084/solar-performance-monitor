"""ML residual model: learn what the physics misses, and use it only if it earns its place.

A gradient-boosted model predicts each interval's actual/expected ratio from irradiance,
its one-hour average (a large array averages passing clouds that a point sensor sees
sharply), temperature and sun position. It's trained only on days the detector called
healthy, so it learns the site's normal quirks, not its faults.

Adoption is decided per site, on data the model never saw:

1. Fit on healthy days before a holdout period (the last quarter of the data).
2. On the holdout's healthy days, compare with physics alone: 15-min error and the
   day-to-day scatter of the performance index (what detection runs on).
3. Adopt only if both improve by at least `MIN_GAIN`. Then refit on all healthy days.

The decision and its numbers are saved in meta.json and shown in the app. On site 2107's
real data it cuts held-out 15-min error from about 13% to 11% and daily scatter by about
9%. On the demo sites there's nothing systematic left to learn, so it isn't adopted.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pvlib

from .config import Site

MIN_GAIN = 0.03          # relative improvement required on both metrics
HOLDOUT_FRACTION = 0.25  # last quarter of the data is the test period
MIN_TRAIN_ROWS = 5000
FEATURES = ["poa", "poa_1h", "temp", "zenith", "azimuth"]


def features(out: pd.DataFrame, site: Site) -> pd.DataFrame:
    loc = pvlib.location.Location(site.latitude, site.longitude, site.timezone, site.elevation_m)
    local = out.index.tz_localize(site.timezone, ambiguous="NaT", nonexistent="NaT")
    sp = loc.get_solarposition(local + pd.Timedelta(minutes=7.5))
    poa = out["poa_irradiance"]
    temp = out["ambient_temp"] if "ambient_temp" in out else pd.Series(np.nan, index=out.index)
    return pd.DataFrame({
        "poa": poa,
        "poa_1h": poa.rolling(4, center=True, min_periods=1).mean(),
        "temp": temp,
        "zenith": sp["apparent_zenith"].to_numpy(),
        "azimuth": sp["azimuth"].to_numpy(),
    }, index=out.index)


def _fit(X: pd.DataFrame, ratio: pd.Series):
    from sklearn.ensemble import HistGradientBoostingRegressor
    return HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, min_samples_leaf=400,
                                         l2_regularization=1.0, random_state=0).fit(X, ratio)


def _predict(model, X: pd.DataFrame, expected: pd.Series, ac_cap: float) -> pd.Series:
    ratio = pd.Series(1.0, index=X.index)
    ok = X[["poa", "zenith"]].notna().all(axis=1) & (expected > 0)
    if ok.any():
        ratio[ok] = model.predict(X[ok])
    return (expected * ratio.clip(0.5, 1.5)).clip(upper=ac_cap)


def _daily_scatter(actual: pd.Series, expected: pd.Series, poa: pd.Series, days) -> float:
    day = actual.index.normalize()
    sunny = (poa > 200) & actual.notna()
    pi = actual.where(sunny).groupby(day).sum() / expected.where(sunny).groupby(day).sum()
    pi = pi[pi.index.isin(days)].replace([np.inf, -np.inf], np.nan).dropna()
    if len(pi) < 20:
        return float("nan")
    dev = pi / pi.rolling(60, min_periods=10).median()
    return float((dev - dev.median()).abs().median() * 1.4826)


def residual_model(out: pd.DataFrame, site: Site, healthy_days) -> tuple[pd.Series | None, dict]:
    """Returns (ML expected power or None, report). None means physics stays."""
    from .expected import rmse_pct

    X = features(out, site)
    act, exp, poa = out["ac_power_kw"], out["expected_ac_kw"], out["poa_irradiance"]
    healthy = pd.Series(out.index.normalize().isin(healthy_days), index=out.index)
    usable = healthy & (poa > 100) & act.notna() & (exp > 0.03 * exp.max()) & X.notna().all(axis=1)
    ratio = (act / exp).clip(0, 2)

    t0, t1 = out.index.min(), out.index.max()
    split = t0 + (t1 - t0) * (1 - HOLDOUT_FRACTION)
    train, test = usable & (out.index < split), usable & (out.index >= split)
    report = {"adopted": False, "holdout_start": str(split.date()), "train_rows": int(train.sum())}
    if train.sum() < MIN_TRAIN_ROWS or test.sum() < MIN_TRAIN_ROWS // 5:
        report["reason"] = "not enough healthy data to train and test"
        return None, report

    cap = float(out.attrs.get("ac_capacity_kw") or act.quantile(0.999))
    ml_test = _predict(_fit(X[train], ratio[train]), X, exp, cap)
    test_days = pd.Index(out.index[test].normalize().unique())
    phys_err = rmse_pct(act, exp, poa, only=test)
    ml_err = rmse_pct(act, ml_test, poa, only=test)
    phys_sd = _daily_scatter(act, exp, poa, test_days)
    ml_sd = _daily_scatter(act, ml_test, poa, test_days)
    report.update({
        "holdout_nrmse_physics": round(phys_err, 2), "holdout_nrmse_ml": round(ml_err, 2),
        "holdout_daily_scatter_physics": round(phys_sd, 4), "holdout_daily_scatter_ml": round(ml_sd, 4),
    })
    better_err = ml_err < phys_err * (1 - MIN_GAIN)
    better_sd = ml_sd < phys_sd * (1 - MIN_GAIN)
    if not (better_err and better_sd):
        report["reason"] = ("didn't beat physics on held-out data by at least "
                            f"{MIN_GAIN:.0%} on both 15-min error and daily scatter")
        return None, report

    report["adopted"] = True
    report["reason"] = "beat physics on held-out data on both 15-min error and daily scatter"
    return _predict(_fit(X[usable], ratio[usable]), X, exp, cap), report
