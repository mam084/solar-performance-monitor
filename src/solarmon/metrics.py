"""Daily performance index (PI) = actual energy / expected energy.

PI ≈ 1.0 means the site is producing what the weather says it should.
This is the signal that phase 2's detection logic will run on.
"""

from __future__ import annotations

import pandas as pd

MIN_POA_FOR_PI = 200  # W/m²; low-light hours are noisy and add little energy


def daily_performance(df: pd.DataFrame, min_coverage: float = 0.5) -> pd.DataFrame:
    """Daily actual vs expected energy over productive hours.

    Needs columns: ac_power_kw, expected_ac_kw, poa_irradiance.
    Days where less than `min_coverage` of productive intervals have power data
    are marked as data gaps instead of getting a (misleadingly low) PI.
    """
    step_h = df.index.to_series().diff().median() / pd.Timedelta(hours=1)
    sunny = df["poa_irradiance"] > MIN_POA_FOR_PI
    d = df[sunny]
    daily = pd.DataFrame({
        "actual_kwh": d["ac_power_kw"].resample("D").sum(min_count=1) * step_h,
        "expected_kwh": d["expected_ac_kw"].resample("D").sum(min_count=1) * step_h,
        "productive_intervals": sunny.resample("D").sum(),
        "power_coverage": d["ac_power_kw"].notna().resample("D").mean(),
        "poa_kwh_m2": d["poa_irradiance"].resample("D").sum(min_count=1) * step_h / 1000,
    })
    daily["pi"] = daily["actual_kwh"] / daily["expected_kwh"]
    daily["data_gap"] = daily["power_coverage"].fillna(0) < min_coverage
    daily.loc[daily["data_gap"], "pi"] = float("nan")
    return daily[daily["productive_intervals"] > 0]
